"""Signals hidden in comments: the habits of language models and the litter
left behind when an agent's output is pasted in without being read."""

from __future__ import annotations

import re
from collections.abc import Iterator

from vibecheck.cpp import Comment, SourceFile
from vibecheck.discover import Project
from vibecheck.model import INVOLVEMENT, OVERSIGHT, Evidence, Signal, clamp, damp, density, saturate, snippet

EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U0001F000-\U0001F2FF☀-➿⭐⭕⬛⬜"
    "⏩-⏺⌚⌛]"
)
TYPOGRAPHY = re.compile("[—–→←⇒≤≥≠×“”‘’…]")

READER_ADDRESS = re.compile(
    r"\blet['\u2019]s\b"
    r"|^\s*(?:now|here|next|first|finally)\s*,?\s+we\b"
    r"|^\s*step\s*\d+\s*[:.)\-]"
    r"|\bwe(?:'ll| will) (?:now|need|first|then)\b",
    re.I,
)
PLACEHOLDER = re.compile(
    r"\bin a (?:real|production|full|complete|proper|more robust)(?:[- ]world)? "
    r"(?:app|application|implementation|system|program|scenario|setting|environment|code|project|version|game|engine)"
    r"|\bin production\b"
    r"|\bfor (?:simplicity|brevity|the sake of (?:simplicity|brevity))"
    r"|\bfor (?:demo|demonstration|illustration|example|testing) purposes"
    r"|\b(?:simplified|naive|mock|dummy|placeholder|stub) "
    r"(?:version|implementation|approach|example|logic|check|calculation|data|value)s?\b"
    r"|\bplaceholder (?:implementation|logic|code|function)\b"
    r"|\byou (?:would|might|may|should|could|will) (?:want|need|typically|normally|probably|likely)\b"
    r"|\breplace (?:this|with) (?:with )?(?:your|actual|a real|real)\b"
    r"|\b(?:your|actual) (?:implementation|logic|code) (?:here|goes here)\b"
    r"|\bthis is (?:just )?(?:a |an )?(?:simple|basic|simplified|naive|minimal|rough) "
    r"(?:implementation|version|example|approach|placeholder)",
    re.I,
)
ELISION = re.compile(
    r"^\s*\.{3}\s*(?:\w+\s+){0,4}?(?:code|implementation|logic|methods?|functions?|fields?|members?|cases?)\b"
    r"|\b(?:rest of|remainder of) (?:the )?(?:code|implementation|function|file|class|logic|methods?|functions?)\b"
    r"|\b(?:existing|previous|original|other) (?:code|implementation|logic|methods?|functions?)(?: \w+){0,2}? "
    r"(?:here|remains?|unchanged|stays?|goes here|as before|omitted)\b"
    r"|\bomitted for brevity\b"
    r"|\b(?:code|implementation) (?:omitted|elided)\b",
    re.I,
)
CHANGELOG_CAPS = re.compile(r"^\s*(?:FIX(?:ED)?|BUG ?FIX|CHANGED|UPDATED|CRITICAL FIX|KEY FIX)\s*[:\-]")
CHANGELOG = re.compile(
    r"\bnow (?:correctly|properly|safely|actually)\b"
    r"|\b(?:was|were) (?:previously|originally)\b"
    r"|\bpreviously (?:this|we|it|the|was|used)\b"
    r"|\bchanged from \S.{0,40}? to\b"
    r"|\binstead of (?:the )?(?:old|previous|original)\b"
    r"|\b(?:this|the) fix\b"
    r"|\bfixed:"
    r"|\bfix (?:the|a) (?:bug|issue|crash|problem|segfault) (?:where|with|that|in|caused)\b"
    r"|\b(?:the )?(?:bug|issue) was (?:that|caused)\b"
    r"|\bupdated to use\b",
    re.I,
)
SHOUTY = re.compile(r"\b(?:CRITICAL|IMPORTANT|KEY (?:FIX|CHANGE|INSIGHT|POINT))\b\s*[:!]")
BANNER = re.compile(r"^\s*[=\-*#~/]{8,}\s*$|^\s*[=\-]{3,}\s*[\w ]+?\s*[=\-]{3,}\s*$")
DOXYGEN = re.compile(r"[@\\](?:brief|param|return)s?\b")

STOPWORDS = {
    "the", "and", "for", "this", "that", "with", "from", "into", "then", "now", "all", "each",
    "its", "are", "was", "will", "can", "not", "our", "use", "using", "any", "but", "has",
    "have", "out", "one", "two", "it's", "via", "per", "new", "get", "set", "you", "your",
    "through", "over",
}
# Words that make a comment explain *why*, which is exactly what restating ones don't.
RATIONALE = {
    "because", "since", "so", "otherwise", "unless", "until", "when", "why", "avoid", "must",
    "never", "only", "can't", "don't", "won't", "instead", "though", "but", "hack", "workaround",
}
# Comment words that correspond to keywords rather than identifiers.
KEYWORD_SYNONYMS = {
    "loop": {"for", "while"}, "iterate": {"for", "while"}, "check": {"if"}, "checks": {"if"},
    "return": {"return"}, "returns": {"return"}, "otherwise": {"else"},
}
_IDENT = re.compile(r"[A-Za-z_]\w*")
_SUBWORD = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")


def _lines(c: Comment) -> Iterator[tuple[int, str]]:
    for k, text in enumerate(c.text.split("\n")):
        yield c.line + k, text.strip().lstrip("*").strip() if c.block else text.strip().lstrip("/!").strip()


def _code_words(code_line: str) -> set[str]:
    words = set()
    for ident in _IDENT.findall(code_line):
        for sw in _SUBWORD.findall(ident):
            if len(sw) >= 3:
                words.add(sw.lower())
    return words


def _related(word: str, code_words: set[str], keywords: set[str]) -> bool:
    if KEYWORD_SYNONYMS.get(word, set()) & keywords:
        return True
    for cw in code_words:
        if len(word) >= 4 and len(cw) >= 4:
            if word[:4] == cw[:4]:
                return True
        elif word.startswith(cw) or cw.startswith(word):
            return True
    return False


def is_restating(comment_text: str, code_line: str) -> bool:
    """A comment that only repeats the code below it, e.g.
    `// Initialize the buffer` above `init_buffer(buf);`.

    Only capitalised sentences count: terse lowercase notes like
    `// sort by char` are a human habit, not a generated one."""
    text = comment_text.strip()
    words = [w.lower() for w in re.findall(r"[A-Za-z']+", text)]
    if not 3 <= len(words) <= 10 or not text[:1].isupper() or text.endswith(":"):
        return False
    if RATIONALE & set(words):
        return False
    content = [w for w in words if len(w) >= 3 and w not in STOPWORDS]
    if not 2 <= len(content) <= 6:
        return False
    code_words = _code_words(code_line)
    if not code_words:
        return False
    # Narration sits on statements; a label above a definition is a heading.
    if not re.search(r";\s*$|^\s*(?:if|for|while|switch|return)\b", code_line):
        return False
    keywords = set(_IDENT.findall(code_line))
    hits = sum(1 for w in content if _related(w, code_words, keywords))
    return hits >= 1 and hits / len(content) >= 0.5


MAX_EVIDENCE = 200


class Hits:
    def __init__(self) -> None:
        self.count = 0
        self.evidence: list[Evidence] = []

    def add(self, sf: SourceFile, line: int, text: str | None = None) -> None:
        self.count += 1
        if len(self.evidence) < MAX_EVIDENCE:
            self.evidence.append(Evidence(sf.path, line, snippet(text if text is not None else sf.line(line))))


def logical_comments(comments: list[Comment]) -> list[Comment]:
    """Merge runs of own-line // comments into the paragraph they form."""
    merged: list[Comment] = []
    for c in comments:
        prev = merged[-1] if merged else None
        if (prev and not c.block and c.own_line and not prev.block and prev.own_line
                and c.line == prev.end_line + 1):
            merged[-1] = Comment(prev.line, c.end_line, prev.text + "\n" + c.text, False, True)
        else:
            merged.append(c)
    return merged


def collect(project: Project) -> list[Signal]:
    kloc = project.kloc
    restating, reader, placeholder, elision = Hits(), Hits(), Hits(), Hits()
    changelog, shouty, typography, banner, emoji = Hits(), Hits(), Hits(), Hits(), Hits()
    doc_funcs = doc_total = 0
    doc_hits = Hits()

    for sf in project.sources:
        bodies = [(f.line, f.end_line) for f in sf.functions]
        for c in logical_comments(sf.comments):
            # A restating comment is a one-liner sitting right above a
            # statement inside a function. Doc comments (///, /**) describe
            # interfaces, which is their job.
            if (c.line == c.end_line and c.own_line and c.end_line < len(sf.code_lines)
                    and not c.text.startswith(("/", "!", "*"))
                    and any(start < c.line < end for start, end in bodies)):
                target = sf.code_lines[c.end_line]
                if target.strip() and is_restating(c.text.strip(" /*!<"), target):
                    restating.add(sf, c.line)

        for c in sf.comments:
            for line, text in _lines(c):
                if not text:
                    continue
                if READER_ADDRESS.search(text):
                    reader.add(sf, line)
                if PLACEHOLDER.search(text):
                    placeholder.add(sf, line)
                if ELISION.search(text):
                    elision.add(sf, line)
                if CHANGELOG_CAPS.search(text) or CHANGELOG.search(text):
                    changelog.add(sf, line)
                if SHOUTY.search(text):
                    shouty.add(sf, line)
                if TYPOGRAPHY.search(text):
                    typography.add(sf, line)
                if c.line == c.end_line and BANNER.search(text):
                    banner.add(sf, line)
                if EMOJI.search(text):
                    emoji.add(sf, line)

        for s in sf.strings:
            if EMOJI.search(s.text):
                emoji.add(sf, s.line)

        if not sf.is_header:
            ends = {c.end_line: c for c in sf.comments}
            for f in sf.functions:
                doc_total += 1
                c = ends.get(f.line - 1) or ends.get(f.line - 2)
                if c and DOXYGEN.search(c.text):
                    doc_funcs += 1
                    doc_hits.add(sf, f.line)

    def per_kloc(h: Hits, half: float, full: int) -> float:
        return saturate(density(h.count, kloc), half) * damp(h.count, full)

    doc_frac = doc_funcs / doc_total if doc_total else 0.0
    return [
        Signal(
            "restating-comments", "Comments that restate the next line of code", INVOLVEMENT, 0.25,
            per_kloc(restating, 10, 5),
            f"{restating.count} comments ({density(restating.count, kloc):.1f}/kLOC) just repeat the code they annotate",
            restating.evidence, {"count": restating.count},
        ),
        Signal(
            "reader-address", "Comments narrating to a reader (\"Let's…\", \"Now we…\", \"Step 1:\")",
            INVOLVEMENT, 0.3, per_kloc(reader, 3, 3),
            f"{reader.count} tutorial-style comments", reader.evidence, {"count": reader.count},
        ),
        Signal(
            "emoji", "Emoji in output strings or comments", INVOLVEMENT, 0.45, per_kloc(emoji, 2, 3),
            f"{emoji.count} strings/comments contain emoji", emoji.evidence, {"count": emoji.count},
        ),
        Signal(
            "typography", "Typeset punctuation in comments (— → ≤ “ ”)", INVOLVEMENT, 0.3,
            per_kloc(typography, 3, 3),
            f"{typography.count} comments use characters people rarely type in an editor",
            typography.evidence, {"count": typography.count},
        ),
        Signal(
            "shouty-annotations", "CRITICAL:/IMPORTANT: annotations", INVOLVEMENT, 0.25, per_kloc(shouty, 1.5, 2),
            f"{shouty.count} shouted annotations", shouty.evidence, {"count": shouty.count},
        ),
        Signal(
            "banner-comments", "Decorative section banners", INVOLVEMENT, 0.1, per_kloc(banner, 4, 4),
            f"{banner.count} banner comments", banner.evidence, {"count": banner.count},
        ),
        Signal(
            "doxygen-everywhere", "Doxygen blocks on nearly every function", INVOLVEMENT, 0.15,
            clamp((doc_frac - 0.5) / 0.4) if doc_total >= 6 else 0.0,
            f"{doc_funcs}/{doc_total} functions in source files carry @brief/@param blocks",
            doc_hits.evidence, {"documented": doc_funcs, "functions": doc_total},
        ),
        Signal(
            "placeholder-comments", "Placeholder/tutorial caveats (\"in a real application…\")", OVERSIGHT, 0.5,
            per_kloc(placeholder, 2, 3),
            f"{placeholder.count} comments admit the code is a stand-in", placeholder.evidence,
            {"count": placeholder.count},
        ),
        Signal(
            "elision-leftovers", "Elided-code leftovers (\"// ... rest of the code\")", OVERSIGHT, 0.6,
            saturate(elision.count, 1),
            f"{elision.count} comments where generated code was abbreviated and pasted as-is",
            elision.evidence, {"count": elision.count},
        ),
        Signal(
            "changelog-comments", "Comments describing edits instead of code (\"FIXED:\", \"now correctly…\")",
            OVERSIGHT, 0.35, per_kloc(changelog, 2, 3),
            f"{changelog.count} comments narrate a change history", changelog.evidence,
            {"count": changelog.count},
        ),
    ]
