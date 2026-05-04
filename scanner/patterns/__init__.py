"""패턴 탐지기 레지스트리."""
from __future__ import annotations

from scanner.patterns.base import EntrySignal, PatternDetector, PatternResult
from scanner.patterns.box_breakout import BoxBreakoutDetector
from scanner.patterns.double_bottom import DoubleBottomDetector
from scanner.patterns.golden_cross import GoldenCrossDetector
from scanner.patterns.pullback import PullbackDetector

ALL_DETECTORS: list[PatternDetector] = [
    DoubleBottomDetector(),
    GoldenCrossDetector(),
    BoxBreakoutDetector(),
    PullbackDetector(),
]

_DETECTOR_MAP: dict[str, PatternDetector] = {d.name: d for d in ALL_DETECTORS}


def get_detector(name: str) -> PatternDetector | None:
    """이름으로 탐지기를 반환한다. 없으면 None."""
    return _DETECTOR_MAP.get(name)


__all__ = [
    "PatternDetector",
    "PatternResult",
    "EntrySignal",
    "ALL_DETECTORS",
    "get_detector",
    "DoubleBottomDetector",
    "GoldenCrossDetector",
    "BoxBreakoutDetector",
    "PullbackDetector",
]
