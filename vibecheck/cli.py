"""Command line entry point."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from vibecheck import __version__
from vibecheck.report import Style, render, render_summary, to_json
from vibecheck.scoring import analyze


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="vibecheck",
        description="Estimate how vibe-coded a C/C++ project is: how much of it looks AI-generated, "
        "and how much it shows signs that nobody reviewed it.",
    )
    p.add_argument("paths", nargs="*", type=Path, default=[Path(".")], help="project directories (default: .)")
    p.add_argument("--json", action="store_true", help="print machine-readable JSON")
    p.add_argument("--no-git", action="store_true", help="ignore git history; scan files on disk")
    p.add_argument("-x", "--exclude", action="append", default=[], metavar="GLOB",
                   help="skip matching paths (repeatable; also read from .vibecheckignore)")
    p.add_argument("-n", "--evidence", type=int, default=3, metavar="N", help="evidence lines per signal (default 3)")
    p.add_argument("-v", "--verbose", action="store_true", help="show all evidence")
    p.add_argument("--color", choices=("auto", "always", "never"), default="auto")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    for path in args.paths:
        if not path.is_dir():
            print(f"vibecheck: {path} is not a directory", file=sys.stderr)
            return 2

    results = [analyze(path, use_git=not args.no_git, exclude=tuple(args.exclude)) for path in args.paths]

    if args.json:
        print(to_json(results))
        return 0

    color = args.color == "always" or (args.color == "auto" and sys.stdout.isatty() and "NO_COLOR" not in os.environ)
    style = Style(color)
    blocks = [render(r, style, max_evidence=args.evidence, show_all=args.verbose) for r in results]
    print("\n\n".join(blocks))
    if len(results) > 1:
        print()
        print(render_summary(results, style))
    return 0
