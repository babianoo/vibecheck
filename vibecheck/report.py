"""Render results for a terminal or as JSON."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from vibecheck.model import INVOLVEMENT, OVERSIGHT
from vibecheck.scoring import Result


class Style:
    def __init__(self, color: bool) -> None:
        self.color = color

    def _wrap(self, code: str, text: str) -> str:
        return f"\x1b[{code}m{text}\x1b[0m" if self.color else text

    def bold(self, t: str) -> str:
        return self._wrap("1", t)

    def dim(self, t: str) -> str:
        return self._wrap("2", t)

    def score(self, value: float, text: str) -> str:
        code = "32" if value < 15 else "33" if value < 35 else "38;5;208" if value < 60 else "31"
        return self._wrap(code, text)


def display_path(path: str) -> str:
    p = Path(path)
    if p.is_relative_to(Path.cwd()):
        return str(p.relative_to(Path.cwd()))
    if p.is_relative_to(Path.home()):
        return f"~/{p.relative_to(Path.home())}"
    return path


def bar(value: float, width: int = 24) -> str:
    filled = round(value / 100 * width)
    return "█" * filled + "░" * (width - filled)


def render(result: Result, style: Style, max_evidence: int = 3, show_all: bool = False) -> str:
    st = result.stats
    out = [style.bold(f"vibecheck · {display_path(result.path)}")]
    facts = [f"{st['source_files']} C/C++ files", f"{st['loc'] / 1000:.1f} kLOC"]
    facts.append(f"{st['commits']} commits" if st["git"] else "no git history")
    if st["skipped_sources"]:
        facts.append(f"{st['skipped_sources']} vendored/generated files skipped")
    out.append(style.dim("  " + " · ".join(facts) + f" · confidence: {result.confidence}"))
    out.append("")

    def row(label: str, value: float, extra: str = "") -> str:
        return f"  {label:<18} {style.score(value, bar(value))} {style.bold(f'{value:3.0f}')}{extra}"

    out.append(row("Vibe score", result.vibe, "  " + style.score(result.vibe, style.bold(result.verdict))))
    out.append(row("AI involvement", result.involvement))
    out.append(row("Oversight deficit", result.oversight))
    out.append(style.dim(f"  {result.blurb}"))

    for axis, heading in ((INVOLVEMENT, "Signs of AI involvement"), (OVERSIGHT, "Signs of missing oversight")):
        fired = result.fired(axis)
        out.append("")
        out.append(style.bold(f"  {heading}"))
        if not fired:
            out.append(style.dim("    nothing notable"))
            continue
        for s in fired:
            out.append(f"    {style.score(s.contribution * 100, f'+{s.contribution * 100:4.1f}')}  {s.title}")
            out.append(style.dim(f"           {s.detail}"))
            limit = len(s.evidence) if show_all else max_evidence
            for ev in s.evidence[:limit]:
                text = f"  {ev.text}" if ev.text else ""
                out.append(f"           {style.dim('·')} {ev.location()}{style.dim(text)}")
            if len(s.evidence) > limit:
                out.append(style.dim(f"           … {len(s.evidence) - limit} more (-v to show all)"))

    for err in result.errors:
        out.append("")
        out.append(f"  ! {err}")
    return "\n".join(out)


def render_summary(results: list[Result], style: Style) -> str:
    width = max(len(display_path(r.path)) for r in results)
    out = [style.bold(f"  {'project':<{width}}   vibe  involv  oversight  verdict")]
    for r in sorted(results, key=lambda r: -r.vibe):
        out.append(
            f"  {display_path(r.path):<{width}}   {style.score(r.vibe, f'{r.vibe:4.0f}')}  {r.involvement:6.0f}  "
            f"{r.oversight:9.0f}  {style.score(r.vibe, r.verdict)}{style.dim(f' ({r.confidence} confidence)')}"
        )
    return "\n".join(out)


def to_json(results: list[Result]) -> str:
    def encode(r: Result) -> dict:
        d = asdict(r)
        d["vibe"], d["involvement"], d["oversight"] = (round(r.vibe, 1), round(r.involvement, 1), round(r.oversight, 1))
        for s, sd in zip(r.signals, d["signals"]):
            sd["strength"] = round(s.strength, 3)
            sd["contribution"] = round(s.contribution, 3)
        return d

    return json.dumps([encode(r) for r in results], indent=2, ensure_ascii=False)
