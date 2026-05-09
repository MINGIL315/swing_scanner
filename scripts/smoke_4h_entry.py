"""4h 전환 smoke test — 4개 패턴 detector 의 entry_signal 호출 검증."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from scanner.kr.patterns.box_breakout import BoxBreakoutDetector
from scanner.kr.patterns.double_bottom import DoubleBottomDetector
from scanner.kr.patterns.golden_cross import GoldenCrossDetector
from scanner.kr.patterns.pullback import PullbackDetector


def main() -> None:
    dates = [date.today() - timedelta(days=60 - i) for i in range(60)]
    daily = pd.DataFrame({
        "date": dates,
        "open":   [100 + i * 0.5 for i in range(60)],
        "high":   [102 + i * 0.5 for i in range(60)],
        "low":    [98 + i * 0.5 for i in range(60)],
        "close":  [101 + i * 0.5 for i in range(60)],
        "volume": [10000 + i * 100 for i in range(60)],
    })

    times = [datetime.now() - timedelta(days=22 - i) for i in range(22)]
    intraday = pd.DataFrame({
        "datetime": times,
        "open":   [200 + i for i in range(22)],
        "high":   [202 + i for i in range(22)],
        "low":    [198 + i for i in range(22)],
        "close":  [201 + i for i in range(22)],
        "volume": [50000 + i * 500 for i in range(22)],
    })

    for det_cls in (DoubleBottomDetector, GoldenCrossDetector, BoxBreakoutDetector, PullbackDetector):
        det = det_cls()
        sig = det.entry_signal(daily, intraday_df=intraday)
        print(f"{det.name:18s} strength={sig.strength:5.1f}  signals={sig.signals}")


if __name__ == "__main__":
    main()
