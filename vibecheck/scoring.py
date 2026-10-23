"""Turn signals into the two axis scores and an overall vibe score.

Each axis combines its signals as a noisy-OR: a signal with contribution c
removes a fraction c of the remaining "doubt". One overwhelming signal (most
commits co-authored by Claude) is enough on its own, and many weak signals
add up without ever exceeding 100.

The vibe score needs AI involvement: messy hand-written code is not
vibe-coded. Missing oversight amplifies it, so AI-heavy code that was
clearly reviewed lands in the middle and not at the top.
"""

from __future__ import annotations

import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from vibecheck import collectors
from vibecheck.discover import Project, load_project
from vibecheck.model import INVOLVEMENT, OVERSIGHT, Signal


@dataclass
class Result:
    path: str
    involvement: float
    oversight: float
    vibe: float
    verdict: str
    blurb: str
    confidence: str
    signals: list[Signal]
    stats: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def fired(self, axis: str | None = None) -> list[Signal]:
        out = [s for s in self.signals if s.contribution > 0.005 and (axis is None or s.axis == axis)]
        return sorted(out, key=lambda s: -s.contribution)


def axis_score(signals: list[Signal], axis: str) -> float:
    doubt = 1.0
    for s in signals:
        if s.axis == axis:
            doubt *= 1.0 - min(1.0, max(0.0, s.contribution))
    return 100.0 * (1.0 - doubt)


def vibe_score(involvement: float, oversight: float) -> float:
    return involvement * (0.4 + 0.6 * oversight / 100.0)


def verdict(vibe: float, involvement: float, oversight: float) -> tuple[str, str]:
    if involvement >= 35 and oversight < 25:
        return "AI-assisted, looks reviewed", "AI was clearly involved, but the result looks curated."
    if vibe >= 60:
        return "Pure vibes", "Heavily generated, and nobody seems to have read it closely."
    if vibe >= 35:
        return "Vibe-coded", "Substantially AI-generated, with visible gaps in review."
    if vibe >= 15:
        return "Lightly AI-assisted", "Some generated fingerprints, mostly human-shaped."
    if oversight >= 40:
        return "Artisanal chaos", "Little sign of AI, but some human mess."
    return "Artisanal", "Little sign of AI generation."


def confidence(project: Project) -> str:
    kloc, commits = project.kloc, project.commit_count
    if kloc >= 1 and commits >= 10:
        return "high"
    if kloc >= 0.3 or commits >= 5:
        return "medium"
    return "low"


def analyze(path: Path, use_git: bool = True, exclude: tuple[str, ...] = ()) -> Result:
    project = load_project(path, use_git=use_git, exclude=exclude)
    signals: list[Signal] = []
    errors: list[str] = []
    for collector in collectors.ALL:
        name = collector.__name__.rsplit(".", 1)[-1]
        try:
            signals.extend(collector.collect(project))
        except Exception as exc:  # one broken detector should not sink the report
            errors.append(f"{name} collector failed: {exc!r}")
            print(f"vibecheck: {name} collector failed on {path}:\n{traceback.format_exc()}", file=sys.stderr)

    inv = axis_score(signals, INVOLVEMENT)
    ovs = axis_score(signals, OVERSIGHT)
    vibe = vibe_score(inv, ovs)
    label, blurb = verdict(vibe, inv, ovs)
    stats = {
        "source_files": len(project.sources),
        "loc": project.loc,
        "comments": sum(len(s.comments) for s in project.sources),
        "functions": sum(len(s.functions) for s in project.sources),
        "skipped_sources": len(project.skipped_sources),
        "git": project.git,
        "commits": project.commit_count,
    }
    return Result(str(project.root), inv, ovs, vibe, label, blurb, confidence(project), signals, stats, errors)
