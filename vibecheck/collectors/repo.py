"""Signals from the repository's files rather than its code: agent config,
agent status reports, abandoned copies and the README's house style."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from vibecheck.collectors.comments import EMOJI
from vibecheck.discover import Project
from vibecheck.model import INVOLVEMENT, OVERSIGHT, Evidence, Signal, saturate, snippet

AGENT_FILES = {
    "CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", "GEMINI.md", ".cursorrules", ".windsurfrules",
    ".clinerules", ".github/copilot-instructions.md", ".aider.conf.yml", ".aiderignore",
    ".aider.chat.history.md", ".aider.input.history", ".mcp.json",
}
AGENT_DIRS = (".claude/", ".cursor/", ".windsurf/", ".roo/", ".kiro/", ".clinerules/", ".continue/", ".gemini/")

STANDARD_DOCS = {
    "README", "LICENSE", "LICENCE", "CHANGELOG", "CHANGES", "CONTRIBUTING", "CODE_OF_CONDUCT",
    "SECURITY", "AUTHORS", "INSTALL", "NEWS", "HACKING", "COPYING", "SUPPORT", "MAINTAINERS",
    "CONTRIBUTORS", "NOTICE", "PATENTS", "TODO", "ROADMAP", "FAQ", "BUILDING", "CREDITS",
    "THANKS", "HISTORY", "GOVERNANCE", "CITATION",
}
REPORT_WORDS = re.compile(
    r"(?:^|[_\-])(?:SUMMARY|COMPLETE|COMPLETED|COMPLETION|FIX|FIXES|FIXED|IMPLEMENTATION|REFACTOR|"
    r"REFACTORING|PROGRESS|STATUS|ANALYSIS|REPORT|CHANGES|MIGRATION|NEXT_STEPS|DONE|RESULTS|AUDIT|"
    r"REVIEW|DEBUG|DEBUGGING|INVESTIGATION|FINDINGS|IMPROVEMENTS|ENHANCEMENTS|UPDATES?|SOLUTION|"
    r"VERIFICATION|TESTING|QUICKSTART|QUICK_START|SETUP|PLAN)(?:$|[_\-])"
)
REPORT_LOWER = re.compile(
    r"(?:implementation|fix(?:es)?|refactor(?:ing)?|migration|debug(?:ging)?|progress|status|completion|changes)"
    r"[_\-](?:summary|report|notes|log|plan|complete|status)",
    re.I,
)
CODE_EXTS = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".py", ".sh", ".js", ".ts"}
LEFTOVER_STEM = re.compile(
    r"(?:[_\-. ](?:old|bak|backup|copy|orig|original|new|fixed|final|temp|tmp|broken|working|alt|v\d+)"
    r"|\s\(\d+\)| copy(?: \d+)?)$",
    re.I,
)
SCRATCH_PREFIX = re.compile(r"^(?:debug|fix|try|temp|tmp|scratch)_\w+$", re.I)
# Throwaway scripts an agent writes to poke at the program it is building.
SCRATCH_SCRIPT = re.compile(r"^(?:test|verify|check|quick|simple|demo|run)_\w+$", re.I)
SCRIPT_EXTS = (".py", ".sh", ".js")
TEST_DIRS = {"test", "tests", "testing", "unittests", "unit_tests", "t", "spec", "specs"}
BACKUP_SUFFIX = (".bak", ".orig", ".rej", "~", ".old", ".backup")

README = re.compile(r"^readme(?:\.\w+)?$", re.I)
BUZZWORDS = re.compile(
    r"\b(comprehensive|robust|seamless(?:ly)?|leverag\w*|cutting[- ]edge|blazing(?:ly)?[- ]fast|"
    r"production[- ]ready|enterprise[- ]grade|state[- ]of[- ]the[- ]art|powerful|intuitive|effortless(?:ly)?|"
    r"elegant(?:ly)?|delv\w+|showcas\w+|feature[- ]rich|user[- ]friendly)\b",
    re.I,
)
TREE = re.compile(r"[├└]──")
CHECKLIST = re.compile(r"^\s*[-*]\s*(?:✅|✔️?|✨|🚀|⚡|🎯|🔥)")


def _agent_files(project: Project) -> list[Evidence]:
    found = {f for f in project.files if f in AGENT_FILES or f.startswith(AGENT_DIRS)}
    # Agent config is often git-ignored; it still tells us how the code was made.
    for name in AGENT_FILES:
        if (project.root / name).is_file():
            found.add(name)
    for d in AGENT_DIRS:
        if (project.root / d).is_dir():
            found.add(d)
    dirs = {d for d in AGENT_DIRS if any(f.startswith(d) for f in found)}
    collapsed = sorted({f for f in found if not f.startswith(tuple(dirs))} | dirs)
    return [Evidence(f, None, "agent configuration") for f in collapsed]


def _is_report(path: str) -> bool:
    p = PurePosixPath(path)
    if p.suffix.lower() not in (".md", ".txt", ".markdown"):
        return False
    stem = p.stem
    if stem.upper() in STANDARD_DOCS or README.match(p.name):
        return False
    if re.fullmatch(r"[A-Z0-9][A-Z0-9_\-]*", stem) and REPORT_WORDS.search(stem):
        return True
    return bool(REPORT_LOWER.search(stem))


def _is_leftover(path: str) -> bool:
    p = PurePosixPath(path)
    if p.name.endswith(BACKUP_SUFFIX):
        return True
    if p.suffix.lower() not in CODE_EXTS:
        return False
    stem = p.stem
    if LEFTOVER_STEM.search(stem):
        return True
    in_test_dir = any(part.lower() in TEST_DIRS for part in p.parts[:-1])
    if SCRATCH_PREFIX.match(stem) and not in_test_dir:
        return True
    return bool(SCRATCH_SCRIPT.match(stem) and p.suffix in SCRIPT_EXTS and not in_test_dir)


def _readme_style(project: Project) -> tuple[float, list[Evidence], dict]:
    emoji_heads, trees, checklist = [], [], []
    buzz: dict[str, Evidence] = {}
    for rel in project.files:
        if not README.match(PurePosixPath(rel).name):
            continue
        try:
            text = (project.root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            ev = Evidence(rel, n, snippet(line))
            if line.lstrip().startswith("#") and EMOJI.search(line):
                emoji_heads.append(ev)
            if TREE.search(line) and not trees:
                trees.append(ev)
            if CHECKLIST.search(line):
                checklist.append(ev)
            for m in BUZZWORDS.finditer(line):
                buzz.setdefault(m.group(1).lower()[:6], ev)
    strength = (
        0.45 * min(1.0, len(emoji_heads) / 3)
        + 0.2 * bool(trees)
        + 0.25 * min(1.0, len(buzz) / 3)
        + 0.1 * min(1.0, len(checklist) / 3)
    )
    evidence = emoji_heads[:5] + trees + list(buzz.values())[:5] + checklist[:3]
    metrics = {"emoji_headings": len(emoji_heads), "tree_diagram": bool(trees),
               "buzzwords": len(buzz), "emoji_checklist": len(checklist)}
    return strength, evidence, metrics


def collect(project: Project) -> list[Signal]:
    agents = _agent_files(project)
    reports = [Evidence(f, None, "agent-style status report") for f in project.files if _is_report(f)]
    leftovers = [Evidence(f, None, "abandoned copy / scratch file") for f in project.files if _is_leftover(f)]
    readme_strength, readme_ev, readme_metrics = _readme_style(project)
    parts = []
    if readme_metrics["emoji_headings"]:
        parts.append(f"{readme_metrics['emoji_headings']} emoji headings")
    if readme_metrics["tree_diagram"]:
        parts.append("a project-tree diagram")
    if readme_metrics["buzzwords"]:
        parts.append(f"{readme_metrics['buzzwords']} marketing buzzwords")
    if readme_metrics["emoji_checklist"]:
        parts.append(f"{readme_metrics['emoji_checklist']} emoji checklist items")

    return [
        Signal(
            "agent-config", "AI agent configuration files", INVOLVEMENT, 0.35, 1.0 if agents else 0.0,
            f"found {', '.join(e.path for e in agents)}" if agents else "none found", agents,
        ),
        Signal(
            "readme-style", "README in LLM house style", INVOLVEMENT, 0.4, readme_strength,
            "README has " + ", ".join(parts) if parts else "README looks unremarkable",
            readme_ev, readme_metrics,
        ),
        Signal(
            "status-reports", "Agent status reports committed (IMPLEMENTATION_SUMMARY.md…)", OVERSIGHT, 0.5,
            saturate(len(reports), 1.5), f"{len(reports)} report-style documents", reports,
            {"count": len(reports)},
        ),
        Signal(
            "leftover-files", "Abandoned copies and scratch files (main_old.cpp, debug_x.py…)", OVERSIGHT, 0.4,
            saturate(len(leftovers), 2), f"{len(leftovers)} leftover files", leftovers,
            {"count": len(leftovers)},
        ),
    ]
