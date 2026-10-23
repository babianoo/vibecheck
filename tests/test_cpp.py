from vibecheck.cpp import SourceFile, find_functions, lex


def names(code: str) -> list[str]:
    return [f.name for f in SourceFile.parse("x.cpp", code).functions]


def test_lex_preserves_offsets_and_lines():
    src = 'int a; // hi "there"\n/* multi\nline */ char *s = "a // b";\n'
    code, comments, strings = lex(src)
    assert len(code) == len(src)
    assert code.count("\n") == src.count("\n")
    assert [c.text for c in comments] == [' hi "there"', " multi\nline "]
    assert [s.text for s in strings] == ["a // b"]
    assert "//" not in code and "hi" not in code


def test_comment_positions():
    _, comments, _ = lex("x = 1; // trailing\n  // own line\n")
    assert [(c.line, c.own_line) for c in comments] == [(1, False), (2, True)]


def test_raw_strings_and_char_literals():
    src = 'auto s = R"xy(he said ")" // no)xy"; char q = \'"\'; char e = \'\\\'\'; int n = 1\'000\'000;'
    code, comments, strings = lex(src)
    assert comments == []
    assert strings[0].text == 'he said ")" // no'
    assert "1'000'000" in code


def test_line_splice_continues_comment():
    _, comments, _ = lex("// one \\\ntwo\nint x;\n")
    assert len(comments) == 1 and comments[0].end_line == 2


def test_unterminated_input_does_not_crash():
    for src in ['"abc', "/* never closed", "'", 'R"x(abc', "// end", "a / b"]:
        code, _, _ = lex(src)
        assert len(code) == len(src)


def test_functions_basic_and_methods():
    src = """
static int helper(int x) { return x; }
namespace { int hidden() { return 1; } }
class Foo : public Bar {
public:
    Foo(int x) : a_(x), b_{x} { }
    int get() const override { auto f = [](int y) { return y; }; return f(a_); }
    ~Foo() {}
private:
    int a_, b_;
};
int Foo::method(int a) noexcept { if (a) { FOREACH(x) { } } std::vector<int> v{1, 2}; return 0; }
template <typename T> T max_of(T a, T b) { return a > b ? a : b; }
bool operator==(const Foo& a, const Foo& b) { return true; }
int main(void) { return 0; }
"""
    funcs = {f.name: f for f in SourceFile.parse("x.cpp", src).functions}
    assert list(funcs) == ["helper", "hidden", "Foo", "get", "~Foo", "Foo::method", "max_of", "operator==", "main"]
    assert funcs["helper"].file_local and funcs["hidden"].file_local
    assert not funcs["main"].file_local
    assert funcs["get"].in_class and not funcs["Foo::method"].in_class
    assert "FOREACH" not in funcs


def test_function_lines_and_bodies():
    src = "int\nadd(int a,\n    int b)\n{\n    return a + b;\n}\n"
    (f,) = find_functions(lex(src)[0])
    assert (f.name, f.line, f.end_line) == ("add", 2, 6)
    assert "return a + b" in f.body


def test_not_functions():
    src = """
struct point { int x, y; };
int table[] = { 1, 2, 3 };
struct point p = { .x = 1, .y = 2 };
enum color { RED, GREEN };
extern "C" { int c_api(void); }
#define WRAP(x) { x }
"""
    assert names(src) == []


def test_preprocessor_braces_ignored():
    src = "#define BLOCK { \\\n  foo(); }\nint f(void) { return 0; }\n"
    assert names(src) == ["f"]


def test_marked_unused():
    src = "static void a(void) __attribute__((unused));\n[[maybe_unused]] static void b() {}\n"
    funcs = SourceFile.parse("x.cpp", src).functions
    assert [f.name for f in funcs] == ["b"] and funcs[0].marked_unused
