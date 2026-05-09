"""다양한 윈도우 + 임계값 조합에서 박스 후보 갯수 시뮬.

목적: 30일은 단기 노이즈, 사용자 의견은 40~60일 박스가 의미 있음.
종가 기반 산출(close.max/min) 으로 윈도우별 range 분포 + 임계값별 통과 갯수 산출.
"""
from __future__ import annotations

from datetime import date, timedelta

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
        {"close": r.close} for r in rows
    ])


def _range_pct(df: pd.DataFrame, window: int, recent_days: int = 3) -> float | None:
    """close.max/close.min 기반 range_pct 산출."""
    n = len(df)
    if n < window + recent_days + 1:
        return None
    box_end = n - recent_days - 1
    box_start = box_end - window
    box_df = df.iloc[box_start:box_end + 1]
    mean_p = float(box_df["close"].mean())
    if mean_p == 0:
        return None
    return float((box_df["close"].max() - box_df["close"].min()) / mean_p)


def main() -> None:
    tickers = _kr_tickers()
    print(f"=== 윈도우 × 임계값 그리드 (KOSPI200 {len(tickers)}종목, close 기반) ===\n")

    windows = [20, 30, 40, 45, 50, 60, 75, 90]
    thresholds_pct = [10, 15, 20, 25, 30]

    # 윈도우별 range 분포
    by_window: dict[int, list[float]] = {w: [] for w in windows}
    for t in tickers:
        df = _load_daily(t)
        if df.empty:
            continue
        for w in windows:
            r = _range_pct(df, w)
            if r is not None:
                by_window[w].append(r * 100)

    print(f"{'window':>7} {'min':>5} {'p25':>5} {'med':>5} {'p75':>5} {'max':>6}  통과율(%) by 임계값")
    header = "  ".join(f"≤{t}%" for t in thresholds_pct)
    print(f"{'':>33}  {header}")
    for w in windows:
        vals = sorted(by_window[w])
        if not vals:
            continue
        n = len(vals)
        pass_rates = [
            sum(1 for v in vals if v <= t) / n * 100 for t in thresholds_pct
        ]
        rates_str = "  ".join(f"{r:>4.0f}" for r in pass_rates)
        print(
            f"{w:>7} {vals[0]:>4.0f}% {vals[n//4]:>4.0f}% "
            f"{vals[n//2]:>4.0f}% {vals[3*n//4]:>4.0f}% {vals[-1]:>5.0f}%  {rates_str}"
        )

    # 윈도우 후보 조합별 통과 종목 갯수 (절대 수치)
    print(f"\n절대 통과 종목 수 ({len(tickers)}종목 중):")
    print(f"{'window':>7}  {header}")
    for w in windows:
        vals = sorted(by_window[w])
        if not vals:
            continue
        n = len(vals)
        counts = [sum(1 for v in vals if v <= t) for t in thresholds_pct]
        counts_str = "  ".join(f"{c:>4d}" for c in counts)
        print(f"{w:>7}  {counts_str}")

    print("\n참고:")
    print("  - 박스 후보 = '박스 형성 OK' 단계까지 통과한 종목 수")
    print("  - 최종 패턴 탐지 = 박스 후보 × 돌파 OK × 거래량 1.5 (보통 박스 후보의 5~30%)")
    print("  - 너무 적으면 (≤5건): 임계값/윈도우 너무 빡빡")
    print("  - 너무 많으면 (≥50건): 노이즈 패턴 다수 포함")
    print("  - 적정선: 박스 후보 20~40건 → 최종 패턴 5~15건")


if __name__ == "__main__":
    main()
