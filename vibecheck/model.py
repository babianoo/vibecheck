"""Core data types shared by the collectors, the scorer and the reporters."""

from __future__ import annotations

from dataclasses import dataclass, field

# A project is scored on two independent axes. "Vibe-coded" means both are high:
# a lot of the code looks machine-generated AND nobody seems to have reviewed it.
INVOLVEMENT = "involvement"
OVERSIGHT = "oversight"


@dataclass(frozen=True)
class Evidence:
    path: str
    line: int | None = None
    text: str = ""

    def location(self) -> str:
        return f"{self.path}:{self.line}" if self.line else self.path


@dataclass
class Signal:
    id: str
    title: str
    axis: str
    weight: float  # the most this signal can contribute to its axis, 0..1
    strength: float = 0.0  # how strongly it fired, 0..1
    detail: str = ""
    evidence: list[Evidence] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    @property
    def contribution(self) -> float:
        return self.weight * self.strength


def saturate(x: float, half: float) -> float:
    """Map x >= 0 onto [0, 1), reaching 0.5 at x == half."""
    if x <= 0:
        return 0.0
    return x / (x + half)


def damp(count: int, full: int) -> float:
    """Discount a signal that is backed by only a handful of hits."""
    return min(1.0, count / full)


def density(count: int, kloc: float) -> float:
    """Hits per thousand lines of code, without exploding on tiny projects."""
    return count / max(kloc, 0.25)


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def snippet(text: str, limit: int = 100) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
