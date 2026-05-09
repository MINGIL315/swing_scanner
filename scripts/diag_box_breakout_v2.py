"""box_breakout 박스 산출식 비교 — high/low 기반 vs close-percentile 기반.

high.max()/low.min() 은 단일 wick 의 outlier 에 민감. 종가 기반 percentile 이
실제 '주 거래 가격대' 를 더 잘 반영하는지 분포 비교.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select

from scanner.db.models import OHLCVDaily, Universe
from scanner.db.session import get_session


def _kr_tickers() -> list[str]:
    with get_session() as session:
        return [
            t for (t,) in session.execute(
                select(Universe.ticker)
                .where(Universe.market == "KR")
                .where(Universe.is_active.is_(True))
            ).all()
        ]


def _load_daily(ticker: str, lookback_days: int = 200) -> pd.DataFrame:
    start = date.today() - timedelta(days=lookback_days)
    with get_session() as session:
        rows = list(
            session.execute(
                select(OHLCVDaily)
                .where(OHLCVDaily.ticker == ticker)
                .where(OHLCVDaily.date >= start)
                .order_by(OHLCVDaily.date)
            ).scalars().all()
        )
    return pd.DataFrame([
        {"high": r.high, "low": r.low, "close": r.close} for r in rows
    ])


def _percentile(s: pd.Series, q: float) -> float:
    return float(np.percentile(s, q))


def _box_methods(df: pd.DataFrame) -> dict[str, float]:
    """4가지 산출법으로 30일 박스의 range_pct 산출."""
    n = len(df)
    if n < 34:
        return {}
    box_df = df.iloc[n - 4 - 30:n - 4]  # 최근 RECENT_DAYS=3 + 1 직전의 30일
    mean_p = float(box_df["close"].mean())
    if mean_p == 0:
        return {}

    methods = {}

    # 1. 현재: high.max() / low.min()
    methods["A_hl_extreme"] = (box_df["high"].max() - box_df["low"].min()) / mean_p

    # 2. close 기반 max/min
    methods["B_close_minmax"] = (box_df["close"].max() - box_df["close"].min()) / mean_p

    # 3. close p95 / p5
    methods["C_close_p95_p5"] = (
        _percentile(box_df["close"], 95) - _percentile(box_df["close"], 5)
    ) / mean_p

    # 4. high p95 / low p5 (wick 일부 허용 + outlier 컷)
    methods["D_hl_p95_p5"] = (
        _percentile(box_df["high"], 95) - _percentile(box_df["low"], 5)
    ) / mean_p

    return methods


def main() -> None:
    tickers = _kr_tickers()
    print(f"=== 박스 산출법 비교 (KOSPI200 {len(tickers)}종목, 30일 윈도우) ===\n")

    rows: list[dict] = []
    for t in tickers:
        df = _load_daily(t)
        if df.empty:
            continue
        m = _box_methods(df)
        if m:
            rows.append({"ticker": t, **m})

    n = len(rows)
    print(f"분석 가능 종목: {n}\n")

    methods = ["A_hl_extreme", "B_close_minmax", "C_close_p95_p5", "D_hl_p95_p5"]
    descriptions = {
        "A_hl_extreme":   "high.max() − low.min()  (현재 코드)",
        "B_close_minmax": "close.max() − close.min()",
        "C_close_p95_p5": "close p95 − close p5  (outlier 절단)",
        "D_hl_p95_p5":    "high p95 − low p5     (wick 일부 허용)",
    }

    print(f"{'산출법':30s} {'min':>6s} {'p25':>6s} {'med':>6s} {'p75':>6s} {'max':>7s}  통과율(≤10%/15%/20%)")
    for m in methods:
        vals = sorted([r[m] * 100 for r in rows])
        if not vals:
            continue
        nv = len(vals)
        pass10 = sum(1 for v in vals if v <= 10) / nv * 100
        pass15 = sum(1 for v in vals if v <= 15) / nv * 100
        pass20 = sum(1 for v in vals if v <= 20) / nv * 100
        print(
            f"{descriptions[m]:30s} "
            f"{vals[0]:>5.1f}% {vals[nv//4]:>5.1f}% {vals[nv//2]:>5.1f}% "
            f"{vals[3*nv//4]:>5.1f}% {vals[-1]:>6.1f}%  "
            f"{pass10:>4.0f}% / {pass15:>4.0f}% / {pass20:>4.0f}%"
        )

    print("\nA(현재) vs C(close p95-p5) — 같은 종목에서 산출 차이:")
    diffs = [(r["A_hl_extreme"] - r["C_close_p95_p5"]) * 100 for r in rows]
    diffs.sort()
    nd = len(diffs)
    print(
        f"  A − C: min={diffs[0]:+.1f}%  med={diffs[nd//2]:+.1f}%  max={diffs[-1]:+.1f}%"
    )
    print(f"  → A 가 C 보다 평균 {sum(diffs)/nd:+.1f}%p 크게 측정 (outlier wick 영향)")


if __name__ == "__main__":
    main()
