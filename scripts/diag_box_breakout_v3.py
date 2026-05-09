"""v3 box_breakout 단계별 fail 진단 — KOSPI200 시뮬.

v3 의 5 게이트 + 거래량 게이트를 직접 호출해 통과 종목과 단계별 탈락 분포를 본다.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import select

from scanner.config import (
    BOX_BREAKOUT_BREAK_PCT,
    BOX_BREAKOUT_RANGE_PCT,
    BOX_BREAKOUT_RECENT_DAYS,
    BOX_BREAKOUT_VOLUME_RATIO,
)
from scanner.db.models import OHLCVDaily, Universe
from scanner.db.session import get_session
from scanner.kr.indicators.atr import atr as atr_func
from scanner.kr.indicators.volume import volume_ratio
from scanner.kr.patterns.box_breakout import (
    BoxBreakoutDetector,
    _MAIN_WINDOW,
    _MIN_ROWS,
    _SHORT_COMPRESSION_MAX,
    _SHORT_WINDOW,
    _TOUCH_MIN_BOTTOM,
    _TOUCH_MIN_TOP,
    _check_trend_calmness,
    _count_touches,
    _dynamic_tolerance,
    _extract_pivots,
)


def _kr_tickers() -> list[str]:
    with get_session() as session:
        return [
            t for (t,) in session.execute(
                select(Universe.ticker)
                .where(Universe.market == "KR")
                .where(Universe.is_active.is_(True))
            ).all()
        ]


def _load_daily(ticker: str, lookback_days: int = 500) -> pd.DataFrame:
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
        {"date": r.date, "open": r.open, "high": r.high, "low": r.low,
         "close": r.close, "volume": r.volume}
        for r in rows
    ])


def _trace_stage(df: pd.DataFrame) -> str:
    """단계별 어디서 탈락하는지 추적. 'PASS' / 'data_insufficient' /
    'main_range' / 'short_compression' / 'trend_calmness' / 'touch_count' /
    'no_breakout' / 'volume' 중 하나."""
    n = len(df)
    if n < _MIN_ROWS:
        return "data_insufficient"

    df_r = df.reset_index(drop=True)
    box_end = n - BOX_BREAKOUT_RECENT_DAYS - 1
    main_start = box_end - _MAIN_WINDOW
    short_start = box_end - _SHORT_WINDOW
    if main_start < 0 or short_start < 0:
        return "data_insufficient"

    main_df = df_r.iloc[main_start: box_end + 1].reset_index(drop=True)
    mean_price = float(main_df["close"].mean())
    if mean_price == 0:
        return "main_range"

    box_top = float(main_df["close"].max())
    box_bottom = float(main_df["close"].min())
    range_pct = (box_top - box_bottom) / mean_price
    if range_pct > BOX_BREAKOUT_RANGE_PCT:
        return "main_range"

    short_df = df_r.iloc[short_start: box_end + 1]
    short_mean = float(short_df["close"].mean())
    if short_mean == 0:
        return "short_compression"
    short_range = (float(short_df["close"].max()) - float(short_df["close"].min())) / short_mean
    comp_ratio = short_range / range_pct if range_pct > 0 else 1.0
    if comp_ratio > _SHORT_COMPRESSION_MAX:
        return "short_compression"

    ok_trend, _ = _check_trend_calmness(df_r, box_end)
    if not ok_trend:
        return "trend_calmness"

    atr_series = atr_func(df_r, 14)
    atr_at_end = atr_series.iloc[box_end]
    atr_now = float(atr_at_end) if not pd.isna(atr_at_end) else 0.0
    last_close = float(main_df["close"].iloc[-1])
    atr_pct = atr_now / last_close if last_close > 0 else 0.02

    pivot_high_idx, pivot_low_idx = _extract_pivots(main_df, atr_now)
    tol = _dynamic_tolerance(atr_pct)
    top_touch = _count_touches(pivot_high_idx, main_df["high"], box_top, tol)
    bot_touch = _count_touches(pivot_low_idx, main_df["low"], box_bottom, tol)

    if top_touch < _TOUCH_MIN_TOP or bot_touch < _TOUCH_MIN_BOTTOM:
        return "touch_count"

    recent_df = df_r.iloc[box_end + 1:]
    threshold = box_top * (1 + BOX_BREAKOUT_BREAK_PCT)
    if not (recent_df["close"] > threshold).any():
        return "no_breakout"

    breakout_idx = int((recent_df["close"] > threshold)[recent_df["close"] > threshold].index[-1])
    vr = volume_ratio(df_r["volume"])
    cvr = float(vr.iloc[breakout_idx])
    if pd.isna(cvr) or cvr < BOX_BREAKOUT_VOLUME_RATIO:
        return "volume"

    return "PASS"


def main() -> None:
    tickers = _kr_tickers()
    print(f"=== v3 box_breakout 진단 (KOSPI200 {len(tickers)}종목, _MIN_ROWS={_MIN_ROWS}) ===\n")

    detector = BoxBreakoutDetector()
    stages: Counter[str] = Counter()
    pass_results = []

    for t in tickers:
        df = _load_daily(t)
        if df.empty:
            stages["no_data"] += 1
            continue
        stage = _trace_stage(df)
        stages[stage] += 1
        if stage == "PASS":
            result = detector.detect(df, t)
            if result is not None:
                pass_results.append((t, result))

    print("단계별 분포 (앞에서부터 순차 게이트, 첫 fail 위치 기록):")
    order = [
        "data_insufficient", "main_range", "short_compression",
        "trend_calmness", "touch_count", "no_breakout", "volume", "PASS",
    ]
    for s in order:
        if s in stages:
            print(f"  {s:22s} {stages[s]:>3d}")
    print()

    print(f"PASS: {len(pass_results)}건")
    for t, r in pass_results:
        d = r.details
        print(
            f"  {t}  range={d['range_pct']:.1f}%  comp={d['compression_ratio']:.2f}  "
            f"top_touch={d['top_touch']}  bot_touch={d['bottom_touch']}  "
            f"vol={d['vol_ratio']:.2f}  break_atr={d['break_atr_mult']:.2f}  "
            f"cq={d['candle_quality_ok']}  score={r.raw_score:.1f}"
        )


if __name__ == "__main__":
    main()
