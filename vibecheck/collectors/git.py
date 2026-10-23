"""Signals from git history: who (or what) wrote the commits, how big they
were, and whether the history looks like generate-run-regenerate loops."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from vibecheck.discover import Project, is_excluded_path, is_vendored_file
from vibecheck.model import INVOLVEMENT, OVERSIGHT, Evidence, Signal, clamp, damp, saturate, snippet

MAX_COMMITS = 5000
_RS, _US = "\x1e", "\x1f"
_FORMAT = f"{_RS}%H{_US}%P{_US}%an{_US}%ae{_US}%at{_US}%B{_US}"

AUTHORED_EXTS = {
    ".c", ".cc", ".cpp", ".cxx", ".c++", ".cu", ".h", ".hh", ".hpp", ".hxx", ".h++", ".ipp", ".tpp",
    ".inl", ".cuh", ".py", ".js", ".ts", ".tsx", ".jsx", ".rs", ".go", ".java", ".kt", ".cs",
    ".swift", ".rb", ".php", ".lua", ".sh", ".cmake", ".mk", ".zig", ".nim", ".hs", ".ml", ".qml",
    ".glsl", ".hlsl", ".frag", ".vert", ".asm", ".s",
}
AUTHORED_NAMES = {"CMakeLists.txt", "Makefile", "makefile", "GNUmakefile", "meson.build"}

AI_MARKERS = re.compile(
    r"co-authored-by:[^\n]*(?:claude|anthropic|copilot|cursor|openai|chatgpt|gpt-\d|gemini|aider|devin|"
    r"codex|windsurf|codeium|cline|jules|amazon q)"
    r"|generated (?:with|by) \[?(?:claude|cursor|aider|copilot|codex|chatgpt|gemini)"
    r"|🤖 generated"
    r"|^aider: "
    r"|\(aider\)",
    re.I | re.M,
)
AI_AUTHORS = re.compile(r"claude|copilot|devin|cursor ?agent|codex|jules|aider|sweep|gemini|openhands", re.I)
LLM_VOCAB = re.compile(
    r"\b(?:comprehensive|enhance[ds]?|enhancements?|robust(?:ness)?|streamlin\w*|seamless(?:ly)?|leverag\w*|"
    r"bolster\w*|elevat\w*|facilitat\w*|utiliz\w*|overhaul\w*|delv\w*|intuitive|holistic|"
    r"proper(?:ly)? handl\w*|production[- ]ready)\b",
    re.I,
)
BULLET = re.compile(r"^\s*[-*•]\s+[A-Z][a-z]+", re.M)
MARKDOWN_BODY = re.compile(r"^\s*(?:#{1,3} \S|\*\*[^*\n]+\*\*:?\s*$)", re.M)
FIXY_START = re.compile(r"^\W*(?:try(?:ing)?|attempt(?:ing)?|again|still|actually|hopefully|oops|retry|revert)\b", re.I)
FIXY_SHORT = re.compile(r"^\W*(?:fix|fixes|fixed|fixing)\b", re.I)
FIXY_ANY = re.compile(r"\b(?:again|another (?:fix|attempt|try)|(?:fix|try|attempt) #?\d+|still (?:broken|failing|not))\b", re.I)

BIG_COMMIT_LINES = 800
WEEK = 7 * 24 * 3600


@dataclass
class Commit:
    sha: str
    parents: list[str]
    author: str
    email: str
    time: int
    message: str
    files: list[tuple[int, int, str, str | None]] = field(default_factory=list)  # added, deleted, path, renamed from

    @property
    def subject(self) -> str:
        return self.message.strip().split("\n", 1)[0].strip()

    @property
    def body(self) -> str:
        parts = self.message.strip().split("\n", 1)
        return parts[1] if len(parts) > 1 else ""

    @property
    def is_root(self) -> bool:
        return not self.parents

    def authored(self) -> tuple[int, int]:
        add = dele = 0
        for a, d, path, _ in self.files:
            if is_authored(path):
                add += a
                dele += d
        return add, dele


def is_authored(path: str) -> bool:
    p = PurePosixPath(path)
    return (
        (p.suffix.lower() in AUTHORED_EXTS or p.name in AUTHORED_NAMES)
        and not is_excluded_path(path)
        and not is_vendored_file(path)
    )


_BRACE_RENAME = re.compile(r"^(.*)\{(.*) => (.*)\}(.*)$")


def split_rename(path: str) -> tuple[str | None, str]:
    """numstat writes renames as `old => new` or `dir/{old => new}/rest`."""
    m = _BRACE_RENAME.match(path)
    if m:
        pre, old, new, post = m.groups()
        return (pre + old + post).replace("//", "/"), (pre + new + post).replace("//", "/")
    if " => " in path:
        old, new = path.split(" => ", 1)
        return old, new
    return None, path


def parse_log(output: str) -> list[Commit]:
    commits = []
    for chunk in output.split(_RS):
        if not chunk.strip():
            continue
        fields = chunk.split(_US)
        if len(fields) < 7:
            continue
        sha, parents, author, email, time, message, numstat = fields[:7]
        c = Commit(sha, parents.split(), author, email, int(time or 0), message)
        for line in numstat.splitlines():
            parts = line.split("\t", 2)
            if len(parts) == 3:
                a, d, path = parts
                old, new = split_rename(path)
                c.files.append((int(a) if a.isdigit() else 0, int(d) if d.isdigit() else 0, new, old))
        commits.append(c)
    commits.reverse()  # oldest first
    return commits


def read_history(root: Path) -> list[Commit]:
    try:
        r = subprocess.run(
            ["git", "-C", str(root), "log", "--no-merges", "-M", "--numstat",
             f"--max-count={MAX_COMMITS}", f"--format={_FORMAT}", "--", "."],
            capture_output=True, text=True, errors="replace", timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_log(r.stdout) if r.returncode == 0 else []


def is_ai_commit(c: Commit) -> bool:
    return bool(AI_MARKERS.search(c.message) or AI_AUTHORS.search(c.author) or AI_AUTHORS.search(c.email.split("@")[0]))


def is_llm_styled(c: Commit) -> bool:
    msg, subject = c.message, c.subject
    vocab = len(LLM_VOCAB.findall(msg))
    return (
        len(BULLET.findall(c.body)) >= 3
        or bool(MARKDOWN_BODY.search(c.body))
        or vocab >= 2
        or (vocab >= 1 and len(subject) > 60)
    )


def is_fixy(c: Commit) -> bool:
    s = c.subject
    return bool(FIXY_START.search(s) or (FIXY_SHORT.search(s) and len(s) <= 50) or FIXY_ANY.search(s))


def _ev(c: Commit, note: str = "") -> Evidence:
    text = snippet(c.subject, 80)
    return Evidence(c.sha[:9], None, f"{text}  [{note}]" if note else text)


def _fix_runs(commits: list[Commit]) -> list[list[Commit]]:
    runs, current = [], []
    for c in commits:
        if is_fixy(c):
            current.append(c)
        else:
            if len(current) >= 3:
                runs.append(current)
            current = []
    if len(current) >= 3:
        runs.append(current)
    return runs


def _rewrites(commits: list[Commit]) -> list[tuple[Commit, str]]:
    """Commits that replace most of an existing file in one go."""
    sizes: dict[str, int] = {}
    events = []
    for c in commits:
        for a, d, path, old in c.files:
            if old is not None:
                sizes[path] = sizes.pop(old, 0)
            size = sizes.get(path, 0)
            if is_authored(path) and size >= 40 and a >= 0.6 * size and d >= 0.6 * size:
                events.append((c, path))
            sizes[path] = max(0, size + a - d)
    return events


def _peak_week(commits: list[Commit]) -> tuple[int, str, int]:
    """Most authored lines one author added in any 7-day window (root commits
    excluded, since an initial import is often old code)."""
    best = (0, "", 0)
    by_author: dict[str, list[tuple[int, int]]] = {}
    for c in commits:
        if not c.is_root:
            by_author.setdefault(c.author, []).append((c.time, c.authored()[0]))
    for author, items in by_author.items():
        items.sort()
        lo, total = 0, 0
        for hi in range(len(items)):
            total += items[hi][1]
            while items[hi][0] - items[lo][0] > WEEK:
                total -= items[lo][1]
                lo += 1
            if total > best[0]:
                best = (total, author, items[lo][0])
    return best


def collect(project: Project) -> list[Signal]:
    commits = read_history(project.root) if project.git else []
    n = project.commit_count = len(commits)
    if n == 0:
        note = "no git history" if not project.git else "no commits"
        return [Signal("git-history", "Git history", INVOLVEMENT, 0.0, 0.0, note)]

    ai = [c for c in commits if is_ai_commit(c)]
    styled = [c for c in commits if is_llm_styled(c)]

    non_root = [c for c in commits if not c.is_root]
    added = [(c, c.authored()[0]) for c in non_root]
    total_added = sum(a for _, a in added)
    big = [(c, a) for c, a in added if a >= BIG_COMMIT_LINES]
    big_frac = sum(a for _, a in big) / total_added if total_added else 0.0
    big_strength = saturate(big_frac, 0.5) * damp(len(big), 2) if total_added >= 1500 else 0.0

    runs = _fix_runs(commits)
    in_runs = sum(len(r) for r in runs)

    rewrites = _rewrites(commits)
    rewrite_commits = {c.sha: c for c, _ in rewrites}
    rewrite_frac = len(rewrite_commits) / max(len(non_root), 1)

    peak, peak_author, _ = _peak_week(commits)

    return [
        Signal(
            "ai-commits", "Commits attributed to an AI agent (trailers, bot authors)", INVOLVEMENT, 0.9,
            saturate(len(ai) / n, 0.15),
            f"{len(ai)}/{n} commits ({len(ai) / n:.0%}) carry AI co-author trailers or agent authors",
            [_ev(c) for c in ai[-200:]], {"count": len(ai), "commits": n},
        ),
        Signal(
            "llm-commit-messages", "Commit messages in LLM style (bulleted bodies, \"comprehensive\", \"enhance\")",
            INVOLVEMENT, 0.4, saturate(len(styled) / n, 0.25) * damp(len(styled), 3),
            f"{len(styled)}/{n} commit messages read like generated summaries",
            [_ev(c) for c in styled[-200:]], {"count": len(styled), "commits": n},
        ),
        Signal(
            "big-bang-commits", "Huge single commits after the first", INVOLVEMENT, 0.2, big_strength,
            f"{len(big)} commits each added ≥{BIG_COMMIT_LINES} lines: {big_frac:.0%} of all code added after the first commit",
            [_ev(c, f"+{a} lines") for c, a in sorted(big, key=lambda x: -x[1])[:200]],
            {"count": len(big), "fraction": round(big_frac, 3)},
        ),
        Signal(
            "whole-file-rewrites", "Files repeatedly rewritten wholesale", INVOLVEMENT, 0.3,
            saturate(rewrite_frac, 0.15) * damp(len(rewrite_commits), 3),
            f"{len(rewrite_commits)}/{len(non_root)} commits replace most of an existing file",
            [_ev(c, path) for c, path in rewrites[-200:]], {"commits": len(rewrite_commits), "events": len(rewrites)},
        ),
        Signal(
            "velocity", "Implausible authoring speed", INVOLVEMENT, 0.2, clamp((peak - 5000) / 15000),
            f"peak of {peak:,} code lines added in one week" + (f" by {peak_author}" if peak_author else ""),
            [], {"peak_week_lines": peak},
        ),
        Signal(
            "fix-chains", "Chains of \"fix\"/\"try again\" commits", OVERSIGHT, 0.3,
            saturate(in_runs / n, 0.15) * damp(in_runs, 3),
            f"{len(runs)} chains of ≥3 consecutive fix-attempt commits ({in_runs} commits)",
            [_ev(c) for r in runs for c in r][:200], {"chains": len(runs), "commits": in_runs},
        ),
    ]
