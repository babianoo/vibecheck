"""A small, forgiving C/C++ lexer.

This is not a parser. It separates comments and string literals from code so
detectors can look at each in isolation, and it finds function definitions by
following braces. Odd input must never crash it: anything it does not
understand is treated as plain code.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import PurePosixPath

C_EXTS = {".c"}
CPP_EXTS = {".cc", ".cpp", ".cxx", ".c++", ".cu"}
HEADER_EXTS = {".h", ".hh", ".hpp", ".hxx", ".h++", ".ipp", ".tpp", ".inl", ".cuh"}
SOURCE_EXTS = C_EXTS | CPP_EXTS | HEADER_EXTS


@dataclass
class Comment:
    line: int
    end_line: int
    text: str  # without the // or /* */ delimiters
    block: bool
    own_line: bool  # nothing but whitespace precedes it on its first line


@dataclass
class StringLit:
    line: int
    text: str


@dataclass
class Function:
    name: str
    line: int
    end_line: int
    header: str
    body: str  # code between the braces, comments and strings blanked
    file_local: bool  # static free function or inside an anonymous namespace
    in_class: bool
    marked_unused: bool


def _blank(s: str) -> str:
    return re.sub(r"[^\n]", " ", s)


_INTERESTING = re.compile(r"[/\"'\n]")
_RAW_PREFIX = re.compile(r"(?:^|[^\w])(?:u8|u|U|L)?R$")


def _is_digit_separator(text: str, i: int) -> bool:
    """C++14 digit separators: the ' in 1'000'000 is not a char literal."""
    if i == 0 or i + 1 >= len(text):
        return False
    if not (text[i - 1].isalnum() and text[i + 1].isalnum()):
        return False
    k = i - 1
    while k >= 0 and (text[k].isalnum() or text[k] in "'_."):
        k -= 1
    return text[k + 1].isdigit()


def lex(text: str) -> tuple[str, list[Comment], list[StringLit]]:
    """Return (code, comments, strings).

    `code` is the input with comment bodies and string contents replaced by
    spaces, so offsets and line numbers still line up with the original.
    """
    out: list[str] = []
    comments: list[Comment] = []
    strings: list[StringLit] = []
    i, n, line = 0, len(text), 1
    line_has_code = False

    while i < n:
        m = _INTERESTING.search(text, i)
        if m is None:
            out.append(text[i:])
            break
        j = m.start()
        if j > i:
            chunk = text[i:j]
            out.append(chunk)
            if not line_has_code and chunk.strip():
                line_has_code = True
            i = j
        c = text[i]

        if c == "\n":
            out.append(c)
            line += 1
            line_has_code = False
            i += 1
            continue

        if c == "/":
            nxt = text[i + 1] if i + 1 < n else ""
            if nxt == "/":
                end = i + 2
                while True:
                    k = text.find("\n", end)
                    if k == -1:
                        end = n
                        break
                    if text[k - 1] == "\\":  # a line splice continues the comment
                        end = k + 1
                        continue
                    end = k
                    break
                raw = text[i:end]
                comments.append(Comment(line, line + raw.count("\n"), raw[2:], False, not line_has_code))
                out.append(_blank(raw))
                line += raw.count("\n")
                i = end
                continue
            if nxt == "*":
                k = text.find("*/", i + 2)
                end = n if k == -1 else k + 2
                raw = text[i:end]
                inner = raw[2:-2] if k != -1 else raw[2:]
                comments.append(Comment(line, line + raw.count("\n"), inner, True, not line_has_code))
                out.append(_blank(raw))
                line += raw.count("\n")
                i = end
                continue
            out.append(c)
            line_has_code = True
            i += 1
            continue

        # c is a quote
        if c == "'" and _is_digit_separator(text, i):
            out.append(c)
            i += 1
            continue

        if c == '"' and _RAW_PREFIX.search(text[max(0, i - 4) : i]):
            k = text.find("(", i + 1, i + 18)
            if k != -1 and "\n" not in text[i + 1 : k]:
                delim = text[i + 1 : k]
                close = text.find(")" + delim + '"', k + 1)
                if close == -1:
                    end, inner = n, text[k + 1 :]
                else:
                    end, inner = close + len(delim) + 2, text[k + 1 : close]
                strings.append(StringLit(line, inner))
                out.append('"' + _blank(text[i + 1 : end - 1]) + '"')
                line += text.count("\n", i, end)
                line_has_code = True
                i = end
                continue

        j = i + 1
        while j < n:
            ch = text[j]
            if ch == "\\":
                j += 2
                continue
            if ch == c or ch == "\n":
                break
            j += 1
        j = min(j, n)
        terminated = j < n and text[j] == c
        inner = text[i + 1 : j]
        end = j + 1 if terminated else j
        if c == '"':
            strings.append(StringLit(line, inner))
        out.append(c + _blank(inner) + (c if terminated else ""))
        line += inner.count("\n")
        line_has_code = True
        i = end

    return "".join(out), comments, strings


_PREPROC = re.compile(r"^[ \t]*#(?:[^\n]*\\\n)*[^\n]*", re.M)


def strip_preprocessor(code: str) -> str:
    return _PREPROC.sub(lambda m: _blank(m.group()), code)


# ---------------------------------------------------------------------------
# Function definitions
# ---------------------------------------------------------------------------

_HEAD = re.compile(r"(operator\s*(?:\(\)|[^\s(]+)|~?[A-Za-z_]\w*(?:\s*::\s*~?[A-Za-z_]\w*)*)\s*\(")
_NOT_FUNCS = {
    "if", "for", "while", "switch", "catch", "return", "sizeof", "alignof", "decltype",
    "else", "do", "try", "defined", "static_assert", "new", "delete", "throw", "case",
    "typeid", "noexcept", "alignas", "requires", "co_return", "co_await", "co_yield",
    "constexpr", "namespace", "__attribute__", "__declspec", "_Alignof", "_Static_assert",
    "_Generic", "asm", "__asm__",
}
_TYPE_KW = re.compile(r"\b(struct|class|union|enum|namespace|extern)\b")
_AFTER_PARAMS = re.compile(
    r"(?:\s|const\b|volatile\b|noexcept\b(?:\s*\([^()]*\))?|override\b|final\b|&&?"
    r"|throw\s*\([^()]*\)|->\s*[^{;]+|:.*|try\b|requires\b.*|\[\[.*?\]\])*",
    re.S,
)
_BAD_PREFIX = re.compile(r"[=;(){}\"?+\-/%|^!]")
_ATTRIBUTE = re.compile(r"__attribute__\s*\(\(.*?\)\)|__declspec\s*\([^()]*\)", re.S)
_UNUSED_MARK = re.compile(r"\[\[\s*maybe_unused\s*\]\]|__attribute__\s*\(\(\s*(?:__)?unused")


def _function_header(header: str):
    """If `header` (the text before a `{`) declares a function, return
    (name, prefix, name_offset); otherwise None."""
    h = _ATTRIBUTE.sub(lambda m: " " * len(m.group()), header)
    m = _HEAD.search(h)
    if not m:
        return None
    name = re.sub(r"\s+", "", m.group(1))
    base = name.split("::")[-1].lstrip("~")
    if base in _NOT_FUNCS:
        return None
    prefix = h[: m.start()]
    if _BAD_PREFIX.search(prefix.replace("->", "")):
        return None
    depth = 0
    for k in range(m.end() - 1, len(h)):
        if h[k] == "(":
            depth += 1
        elif h[k] == ")":
            depth -= 1
            if depth == 0:
                break
    else:
        return None
    rest = h[k + 1 :]
    if not _AFTER_PARAMS.fullmatch(rest):
        return None
    # In a constructor's initializer list, `x_{1}` opens a brace too; the real
    # body only follows a closing ) or }.
    if re.match(r"\s*:(?!:)", rest) and not re.search(r"[)}]\s*$", h):
        return None
    return name, prefix, m.start()


def _classify(header: str, parent: str, in_func: bool):
    if parent == "expr":
        return "expr", None
    if not in_func:  # C and C++ have no nested functions (lambdas aren't named)
        f = _function_header(header)
        if f:
            return "func", f
    s = header.strip()
    if s.endswith(("=", ",", "(", "[")) or re.search(r"\breturn$", s):
        return "expr", None
    tk = _TYPE_KW.search(s)
    if tk:
        kw = tk.group(1)
        if kw in ("struct", "class", "union"):
            return "class", None
        if kw == "namespace" and re.search(r"\bnamespace\s*$", s):
            return "anon_ns", None
        return "namespace", None
    if re.search(r"\b(do|else|try)$", s):
        return "block", None
    if re.search(r"[\w>]$", s):  # brace initialisation: Foo f{1}, std::vector<int>{...}
        return "expr", None
    return "block", None


def find_functions(code: str) -> list[Function]:
    """Find function definitions in lexed code (comments/strings blanked)."""
    code2 = strip_preprocessor(code)
    newlines = [m.start() for m in re.finditer("\n", code2)]

    def line_of(pos: int) -> int:
        return bisect.bisect_left(newlines, pos) + 1

    funcs: list[Function] = []
    stack: list[tuple[int, str, object, int]] = []  # (pos, kind, info, saved_last)
    last = -1
    for m in re.finditer(r"[{};]", code2):
        pos, ch = m.start(), m.group()
        if ch == ";":
            last = pos
        elif ch == "{":
            parent = stack[-1][1] if stack else "top"
            in_func = any(k == "func" for _, k, _, _ in stack)
            header = code2[last + 1 : pos]
            kind, info = _classify(header, parent, in_func)
            if kind == "func":
                info = (*info, last + 1, header)
            stack.append((pos, kind, info, last))
            last = pos
        else:
            if not stack:
                last = pos
                continue
            start, kind, info, saved = stack.pop()
            last = saved if kind == "expr" else pos
            if kind != "func":
                continue
            name, prefix, name_off, header_start, header = info
            kinds = [k for _, k, _, _ in stack]
            in_class = "class" in kinds
            local = not in_class and "::" not in name and (
                "anon_ns" in kinds or re.search(r"\bstatic\b", prefix) is not None
            )
            funcs.append(
                Function(
                    name=name,
                    line=line_of(header_start + name_off),
                    end_line=line_of(pos),
                    header=" ".join(header.split()),
                    body=code2[start + 1 : pos],
                    file_local=local,
                    in_class=in_class,
                    marked_unused=bool(_UNUSED_MARK.search(header)),
                )
            )
    return funcs


@dataclass
class SourceFile:
    path: str  # relative, posix
    text: str
    code: str
    comments: list[Comment] = field(repr=False)
    strings: list[StringLit] = field(repr=False)

    @classmethod
    def parse(cls, path: str, text: str) -> "SourceFile":
        code, comments, strings = lex(text)
        return cls(path, text, code, comments, strings)

    @property
    def ext(self) -> str:
        return PurePosixPath(self.path).suffix.lower()

    @property
    def is_header(self) -> bool:
        return self.ext in HEADER_EXTS

    @property
    def is_cpp(self) -> bool:
        if self.ext in CPP_EXTS or self.ext in HEADER_EXTS - {".h"}:
            return True
        if self.ext == ".h":
            return bool(re.search(r"\b(class|namespace|template|std::)\b", self.code))
        return False

    @cached_property
    def lines(self) -> list[str]:
        return self.text.split("\n")

    @cached_property
    def code_lines(self) -> list[str]:
        return self.code.split("\n")

    @cached_property
    def loc(self) -> int:
        return sum(1 for l in self.code_lines if l.strip())

    @cached_property
    def functions(self) -> list[Function]:
        return find_functions(self.code)

    def line(self, n: int) -> str:
        """Original source line, 1-based."""
        return self.lines[n - 1] if 0 < n <= len(self.lines) else ""
