"""Signals in the code itself: dead code, near-duplicate functions and idioms
that suggest nobody with a mental model of the program was in the loop."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import PurePosixPath

from vibecheck.collectors.comments import Hits
from vibecheck.cpp import Function, SourceFile
from vibecheck.discover import Project
from vibecheck.model import INVOLVEMENT, OVERSIGHT, Evidence, Signal, damp, density, saturate, snippet

NEW_NULL_CHECK = re.compile(
    r"(\b[A-Za-z_]\w*(?:(?:->|\.)\w+)*)\s*=\s*new\b(?!\s*\(\s*(?:std\s*::\s*)?nothrow)[^;]*;\s*"
    r"if\s*\(\s*(?:!\s*\1\s*\)|\1\s*==\s*(?:nullptr|NULL|0)\s*\)|(?:nullptr|NULL)\s*==\s*\1\s*\))"
)
IOSTREAM = re.compile(r"\bstd\s*::\s*c(?:out|err)\b|\bc(?:out|err)\s*<<")
STDIO = re.compile(r"\b(?:printf|fprintf|puts)\s*\(")
MALLOC = re.compile(r"\b(?:malloc|calloc|realloc)\s*\(")
NEW = re.compile(r"\bnew\s+[A-Za-z_]")
PRAGMA_ONCE = re.compile(r"^[ \t]*#[ \t]*pragma[ \t]+once\b", re.M)
INCLUDE_GUARD = re.compile(r"^[ \t]*#[ \t]*ifndef[ \t]+(\w+)[ \t]*\n[ \t]*#[ \t]*define[ \t]+\1\b", re.M)

STATEMENT_KEYWORDS = {"return", "case", "else", "throw", "delete", "new", "co_return", "goto", "do"}
KEYWORDS = set(
    """alignas alignof asm auto bool break case catch char char16_t char32_t char8_t class const
    constexpr const_cast continue decltype default delete do double dynamic_cast else enum explicit
    export extern false float for friend goto if inline int long mutable namespace new noexcept
    nullptr operator private protected public register reinterpret_cast return short signed sizeof
    static static_assert static_cast struct switch template this throw true try typedef typeid
    typename union unsigned using virtual void volatile wchar_t while NULL size_t""".split()
)
_TOKEN = re.compile(r"[A-Za-z_]\w*|\d[\w.']*|\S")
MIN_CLONE_TOKENS = 50
MIN_EXACT_TOKENS = 70  # short functions share structure by accident (setters, getters)
SHINGLE = 5
NEAR_CLONE = 0.75


def _tokens(body: str) -> list[str]:
    return _TOKEN.findall(body)


def _normalized(tokens: list[str]) -> tuple[str, ...]:
    out = []
    for t in tokens:
        if t[0].isdigit():
            out.append("N")
        elif t[0].isalpha() or t[0] == "_":
            out.append(t if t in KEYWORDS else "I")
        else:
            out.append(t)
    return tuple(out)


def _shingles(tokens: list[str]) -> frozenset:
    return frozenset(tuple(tokens[i : i + SHINGLE]) for i in range(len(tokens) - SHINGLE + 1))


def find_clones(funcs: list[tuple[SourceFile, Function]]) -> list[tuple[tuple[SourceFile, Function], tuple[SourceFile, Function], float]]:
    """Pairs of functions that are structurally identical (identifiers renamed)
    or share most of their token 5-grams."""
    items = []
    for sf, f in funcs:
        toks = _tokens(f.body)
        if len(toks) >= MIN_CLONE_TOKENS:
            items.append((sf, f, toks, _normalized(toks), _shingles(toks)))
    items.sort(key=lambda it: len(it[2]))

    def copied_module(a, b) -> bool:
        # The same function in two different directories is a file copied
        # between sub-projects, a human habit rather than generation.
        return a[1].name == b[1].name and PurePosixPath(a[0].path).parent != PurePosixPath(b[0].path).parent

    pairs = []
    for i, a in enumerate(items):
        for b in items[i + 1 :]:
            if len(b[2]) * NEAR_CLONE > len(a[2]):
                break
            if copied_module(a, b):
                continue
            if a[3] == b[3]:
                if len(a[2]) >= MIN_EXACT_TOKENS:
                    pairs.append(((a[0], a[1]), (b[0], b[1]), 1.0))
                continue
            inter = len(a[4] & b[4])
            if inter:
                sim = inter / len(a[4] | b[4])
                if sim >= NEAR_CLONE:
                    pairs.append(((a[0], a[1]), (b[0], b[1]), sim))
    return pairs


MACRO_CALL = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\s*\(([^()]*)\)")


def _macro_prefixes(sf: SourceFile) -> set[str]:
    """Identifiers passed to ALL_CAPS macros. G_DEFINE_TYPE(Foo, foo, ...)
    references foo_init and foo_class_init by token pasting."""
    out = set()
    for m in MACRO_CALL.finditer(sf.code):
        out.update(a.strip() for a in m.group(1).split(",") if re.fullmatch(r"\s*[a-z_]\w*\s*", a))
    return out


def _uses(sf: SourceFile, f: Function, macro_prefixes: set[str]) -> int:
    """References to a file-local function outside its definition and prototypes."""
    if any(f.name.startswith(p + "_") for p in macro_prefixes):
        return 1
    count = 0
    pattern = re.compile(r"\b" + re.escape(f.name) + r"\b")
    # A prototype has a return type before the name; a call has nothing or a keyword.
    proto = re.compile(
        r"\s*((?:[\w:<>,\[\]]+[\s*&]+)+)" + re.escape(f.name)
        + r"\s*\([^;{}]*\)\s*(?:__attribute__\s*\(\(.*?\)\)\s*)?",
        re.S,
    )
    for m in pattern.finditer(sf.code):
        line = sf.code.count("\n", 0, m.start()) + 1
        if line == f.line:
            continue
        start = max(sf.code.rfind(";", 0, m.start()), sf.code.rfind("{", 0, m.start()), sf.code.rfind("}", 0, m.start())) + 1
        end = sf.code.find(";", m.end())
        statement = sf.code[start:end] if end != -1 else ""
        decl = proto.fullmatch(statement) if end != -1 and "=" not in statement else None
        if decl and not STATEMENT_KEYWORDS & set(decl.group(1).split()):
            continue
        count += 1
    return count


def collect(project: Project) -> list[Signal]:
    kloc = project.kloc
    null_checks, mixed_io, mixed_alloc, double_guard, dead = Hits(), Hits(), Hits(), Hits(), Hits()
    cpp_files = headers = 0
    all_funcs: list[tuple[SourceFile, Function]] = []

    for sf in project.sources:
        for m in NEW_NULL_CHECK.finditer(sf.code):
            null_checks.add(sf, sf.code.count("\n", 0, m.start()) + 1)

        if sf.is_cpp and not sf.is_header:
            cpp_files += 1
            io, c_io = IOSTREAM.search(sf.code), STDIO.search(sf.code)
            if io and c_io:
                mixed_io.add(sf, sf.code.count("\n", 0, c_io.start()) + 1,
                             "mixes std::cout and printf: " + snippet(sf.line(sf.code.count("\n", 0, c_io.start()) + 1)))
            al, nw = MALLOC.search(sf.code), NEW.search(sf.code)
            if al and nw:
                mixed_alloc.add(sf, sf.code.count("\n", 0, al.start()) + 1,
                                "mixes new and malloc: " + snippet(sf.line(sf.code.count("\n", 0, al.start()) + 1)))

        if sf.is_header:
            headers += 1
            pragma = PRAGMA_ONCE.search(sf.text)
            if pragma and INCLUDE_GUARD.search(sf.code):
                double_guard.add(sf, sf.text.count("\n", 0, pragma.start()) + 1, "#pragma once plus an #ifndef guard")

        prefixes = None
        for f in sf.functions:
            all_funcs.append((sf, f))
            if f.file_local and not f.marked_unused and not sf.is_header:
                if prefixes is None:
                    prefixes = _macro_prefixes(sf)
                if _uses(sf, f, prefixes) > 0:
                    continue
                dead.add(sf, f.line, f"{f.name}() is file-local and never called")

    clones = find_clones(all_funcs)
    clone_tokens = sum(len(_tokens(f.body)) for f in {id(f): f for pair in clones for _, f in pair[:2]}.values())
    total_tokens = sum(len(_tokens(f.body)) for _, f in all_funcs) or 1
    clone_frac = clone_tokens / total_tokens
    clone_evidence = [
        Evidence(a[0].path, a[1].line,
                 f"{a[1].name}() ≈ {b[1].name}() at {b[0].path}:{b[1].line} ({sim:.0%} similar)")
        for a, b, sim in sorted(clones, key=lambda p: -p[2])[:200]
    ]

    mixed = Hits()
    mixed.count = mixed_io.count + mixed_alloc.count
    mixed.evidence = mixed_io.evidence + mixed_alloc.evidence
    return [
        Signal(
            "double-include-guard", "Headers with both #pragma once and an include guard", INVOLVEMENT, 0.15,
            saturate(double_guard.count / max(headers, 1), 0.3) * damp(double_guard.count, 2),
            f"{double_guard.count}/{headers} headers are guarded twice", double_guard.evidence,
            {"count": double_guard.count, "headers": headers},
        ),
        Signal(
            "new-null-check", "Null checks after plain `new` (it throws, it never returns null)", OVERSIGHT, 0.3,
            saturate(null_checks.count, 1.5),
            f"{null_checks.count} dead null checks after new", null_checks.evidence, {"count": null_checks.count},
        ),
        Signal(
            "mixed-idioms", "C and C++ idioms mixed in the same file", OVERSIGHT, 0.15,
            saturate(mixed.count / max(cpp_files, 1), 0.3) * damp(mixed.count, 2),
            f"{mixed.count} C++ files mix iostream/printf or new/malloc", mixed.evidence,
            {"count": mixed.count, "cpp_files": cpp_files},
        ),
        Signal(
            "dead-static-functions", "Unused static functions (compiler warnings ignored)", OVERSIGHT, 0.3,
            saturate(dead.count, 2) * damp(dead.count, 2),
            f"{dead.count} file-local functions are never called", dead.evidence, {"count": dead.count},
        ),
        Signal(
            "duplicate-functions", "Near-duplicate functions", OVERSIGHT, 0.35,
            saturate(clone_frac, 0.15) * damp(len(clones), 2),
            f"{len(clones)} clone pairs covering {clone_frac:.0%} of function code"
            f" ({density(len(clones), kloc):.1f} pairs/kLOC)",
            clone_evidence, {"pairs": len(clones), "fraction": round(clone_frac, 3)},
        ),
    ]
