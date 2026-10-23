from pathlib import Path

import pytest

from vibecheck.collectors import code, comments, git, repo
from vibecheck.collectors.comments import CHANGELOG, ELISION, PLACEHOLDER, READER_ADDRESS, is_restating
from vibecheck.cpp import SourceFile
from vibecheck.discover import Project


def project_of(files: dict[str, str]) -> Project:
    p = Project(root=Path("/nonexistent"), files=sorted(files))
    p.sources = [SourceFile.parse(path, text) for path, text in files.items()]
    return p


def signal(signals, sid):
    return next(s for s in signals if s.id == sid)


@pytest.mark.parametrize("comment, line", [
    ("Initialize the buffer", "init_buffer(buf);"),
    ("Print the result", 'printf("%d", result);'),
    ("Free the buffer", "free(buffer);"),
    ("Close the file", "file.close();"),
    ("Loop through each item", "for (auto& item : items) {"),
])
def test_restating(comment, line):
    assert is_restating(comment, line)


@pytest.mark.parametrize("comment, line", [
    ("caller owns the returned buffer", "init_buffer(buf);"),  # adds information
    ("AnkiConnect implementation", "std::string anki_add(int x)"),  # a heading, not narration
    ("Steps:", "run();"),
    ("x", "x++;"),
    ("sort by occurrences", "VectorSort(&counts, CompareOccurrences);"),  # terse lowercase note
    ("Error check", "if (sock == -1) {"),
    ("Retry because the socket may be half-closed after a timeout", "send_all(sock);"),
    ("unique_ptr so result is deleted when this returns", "std::unique_ptr<SearchResult> result(ptr);"),
])
def test_not_restating(comment, line):
    assert not is_restating(comment, line)


def test_comment_patterns():
    assert READER_ADDRESS.search("Let's compute the hash")
    assert READER_ADDRESS.search("Now we check the bounds")
    assert READER_ADDRESS.search("Step 2: parse input")
    assert not READER_ADDRESS.search("RAII lets an object own the resource")
    assert PLACEHOLDER.search("In a real application you would use a database")
    assert PLACEHOLDER.search("For simplicity, we ignore errors")
    assert not PLACEHOLDER.search("Swap the placeholder hint for the real output")
    assert ELISION.search("... rest of the code remains the same")
    assert ELISION.search("... existing methods")
    assert not ELISION.search("the rest is handled by the caller")
    assert CHANGELOG.search("now correctly handles empty input")
    assert not CHANGELOG.search("handles empty input")
    assert CHANGELOG.search("changed from a vector to a deque")
    assert not CHANGELOG.search("Widgets may only be changed from there.")


def test_comment_collector_counts():
    src = '''
int main() {
    // Initialize the counter
    int counter = 0;
    // Let's start
    // ... rest of the code
    // FIXED: off by one
    // IMPORTANT: keep this
    puts("done ✅");
    return counter;  // see RFC 1234 — section 2
}
'''
    signals = comments.collect(project_of({"main.c": src}))
    counts = {s.id: s.metrics.get("count") for s in signals}
    assert counts["reader-address"] == 1
    assert counts["restating-comments"] == 1
    assert counts["elision-leftovers"] == 1
    assert counts["changelog-comments"] == 1
    assert counts["shouty-annotations"] == 1
    assert counts["emoji"] == 1
    assert counts["typography"] == 1


def test_restating_ignores_comment_paragraphs():
    src = "void f() {\n    // Queues the callback on the UI thread, which then\n    // owns result.\n    queue_result(result);\n}\n"
    assert signal(comments.collect(project_of({"a.c": src})), "restating-comments").metrics["count"] == 0


def test_dead_static_functions():
    src = '''
static int used(int x);
static int unused(void);
static int unused(void) { return 2; }
static int used(int x) { return x; }
static void cb(void) { used(2); }
static void (*table[])(void) = { cb };
[[maybe_unused]] static int quiet(void) { return 0; }
int main(void) { return used(1); }
'''
    dead = signal(code.collect(project_of({"a.c": src})), "dead-static-functions")
    assert dead.metrics["count"] == 1
    assert "unused" in dead.evidence[0].text


def test_class_members_in_anonymous_namespace_are_not_file_local():
    src = "namespace {\nclass Plugin : public Base {\n    void init() override { }\n};\nvoid helper() { }\n}\n"
    dead = signal(code.collect(project_of({"a.cpp": src})), "dead-static-functions")
    assert [e.text for e in dead.evidence] == ["helper() is file-local and never called"]


def test_macro_pasted_functions_are_used():
    src = "G_DEFINE_TYPE(QsAgent, qs_agent, G_TYPE_OBJECT);\nstatic void qs_agent_init(QsAgent* self) { }\n"
    assert signal(code.collect(project_of({"a.c": src})), "dead-static-functions").metrics["count"] == 0


def test_static_functions_in_headers_are_not_dead():
    src = "static inline int helper(int x) { return x; }\n"
    assert signal(code.collect(project_of({"a.h": src})), "dead-static-functions").metrics["count"] == 0


def test_new_null_check():
    src = '''
void f() {
    Foo* a = new Foo();
    if (a == nullptr) { return; }
    Foo* b = new (std::nothrow) Foo();
    if (!b) { return; }
    this->c = new Bar;
    if (!this->c) return;
}
'''
    assert signal(code.collect(project_of({"a.cpp": src})), "new-null-check").metrics["count"] == 2


def test_clones():
    body = ("{ int total = 0; int seen = 0; for (int i = 0; i < n; i++) { if (v[i] > 0) { total += v[i] * 2; seen++; }"
            " else if (v[i] < -10) { total -= v[i] / 3; } else { total -= 1; } } if (seen == 0) { return -1; }"
            " return total + %d; }")
    src = "int a(int* v, int n) " + body % 1 + "\nint b(int* w, int m) " + body.replace("v[", "w[").replace("n;", "m;") % 7
    src += "\nint c(void) { return 3; }\n"
    clones = signal(code.collect(project_of({"a.c": src})), "duplicate-functions")
    assert clones.metrics["pairs"] == 1


def test_copied_modules_across_directories_are_not_clones():
    fn = "int util(int* v, int n) { int t = 0; for (int i = 0; i < n; i++) { if (v[i] > 0) { t += v[i] * 2; } else { t -= 1; } } return t; }\n"
    clones = signal(code.collect(project_of({"hw1/util.c": fn, "hw2/util.c": fn})), "duplicate-functions")
    assert clones.metrics["pairs"] == 0


@pytest.mark.parametrize("path, expected", [
    ("IMPLEMENTATION_SUMMARY.md", True),
    ("docs/FIXES_APPLIED.md", True),
    ("refactor-plan.md", True),
    ("README.md", False),
    ("CHANGELOG.md", False),
    ("notes.md", False),
    ("DESIGN.md", False),
])
def test_status_reports(path, expected):
    assert repo._is_report(path) is expected


@pytest.mark.parametrize("path, expected", [
    ("main_old.cpp", True),
    ("src/parser_v2.c", True),
    ("parser copy.c", True),
    ("debug_loader.py", True),
    ("test_parser.py", True),
    ("tests/test_parser.py", False),
    ("test_list.c", False),
    ("simple_shell.c", False),
    ("main.c.orig", True),
    ("parser.c", False),
])
def test_leftover_files(path, expected):
    assert repo._is_leftover(path) is expected


def test_split_rename():
    assert git.split_rename("src/{json.hpp => lib/json.hpp}") == ("src/json.hpp", "src/lib/json.hpp")
    assert git.split_rename("{a => b}/x.c") == ("a/x.c", "b/x.c")
    assert git.split_rename("old.c => new.c") == ("old.c", "new.c")
    assert git.split_rename("plain.c") == (None, "plain.c")


def test_commit_classifiers():
    c = git.Commit("a" * 40, ["b"], "Dev", "dev@x", 0, "Add parser\n\nCo-Authored-By: Claude <noreply@anthropic.com>")
    assert git.is_ai_commit(c)
    assert git.is_ai_commit(git.Commit("a", [], "copilot-swe-agent[bot]", "x@y", 0, "Fix"))
    assert not git.is_ai_commit(git.Commit("a", [], "Dev", "dev@x", 0, "Add parser"))
    assert git.is_llm_styled(git.Commit("a", [], "D", "d", 0, "Add x\n\n- Add a\n- Update b\n- Remove c"))
    assert git.is_llm_styled(git.Commit("a", [], "D", "d", 0, "Enhance parser with comprehensive error handling"))
    assert not git.is_llm_styled(git.Commit("a", [], "D", "d", 0, "core/window: ensure window cannot be made visible during reload"))
    assert git.is_fixy(git.Commit("a", [], "D", "d", 0, "fix build"))
    assert git.is_fixy(git.Commit("a", [], "D", "d", 0, "try again"))
    assert not git.is_fixy(git.Commit("a", [], "D", "d", 0, "Add tokenizer"))
