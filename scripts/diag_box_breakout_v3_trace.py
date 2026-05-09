"""PR #38 의 4 통과 종목이 v3 의 어느 게이트에서 fail 하는지 추적."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from sqlalchemy import select

from scanner.config import (
    BOX_BREAKOUT_BREAK_PCT,
    BOX_BREAKOUT_RANGE_PCT,
    BOX_BREAKOUT_RECENT_DAYS,
    BOX_BREAKOUT_VOLUME_RATIO,
)
from scanner.db.models import OHLCVDaily
from scanner.db.session import get_session
from scanner.kr.indicators.atr import atr as atr_func
from scanner.kr.indicators.volume import volume_ratio
from scanner.kr.patterns.box_breakout import (
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


# PR #38 통과 종목 + 거래량 미달 1 (000810)
TICKERS_TO_TRACE = ["003490", "011210", "086280", "280360", "000810"]


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


def _trace_detailed(ticker: str, df: pd.DataFrame) -> None:
    n = len(df)
    print(f"\n=== {ticker} (n={n}, _MIN_ROWS={_MIN_ROWS}) ===")
    if n < _MIN_ROWS:
        print(f"  → data_insufficient")
        return

    df_r = df.reset_index(drop=True)
    box_end = n - BOX_BREAKOUT_RECENT_DAYS - 1
    main_start = box_end - _MAIN_WINDOW
    short_start = box_end - _SHORT_WINDOW

    main_df = df_r.iloc[main_start: box_end + 1].reset_index(drop=True)
    mean_price = float(main_df["close"].mean())
    box_top = float(main_df["close"].max())
    box_bottom = float(main_df["close"].min())
    range_pct = (box_top - box_bottom) / mean_price

    print(f"  [1] main_range : {range_pct*100:.1f}% (≤{BOX_BREAKOUT_RANGE_PCT*100:.0f}%) "
          f"{'OK' if range_pct <= BOX_BREAKOUT_RANGE_PCT else 'FAIL'}")
    if range_pct > BOX_BREAKOUT_RANGE_PCT:
        return

    short_df = df_r.iloc[short_start: box_end + 1]
    short_mean = float(short_df["close"].mean())
    short_range = (float(short_df["close"].max()) - float(short_df["close"].min())) / short_mean
    comp = short_range / range_pct if range_pct > 0 else 1.0
    print(f"  [2] compression: {comp:.2f} (≤{_SHORT_COMPRESSION_MAX:.2f}) "
          f"{'OK' if comp <= _SHORT_COMPRESSION_MAX else 'FAIL'}")
    if comp > _SHORT_COMPRESSION_MAX:
        return

    ok_trend, info = _check_trend_calmness(df_r, box_end)
    print(f"  [3] trend      : ma20={info.get('ma20_slope', 0)*100:+.2f}%, "
          f"ma60={info.get('ma60_slope', 0)*100:+.2f}% {'OK' if ok_trend else 'FAIL'}")
    if not ok_trend:
        return

    atr_series = atr_func(df_r, 14)
    atr_now = float(atr_series.iloc[box_end]) if not pd.isna(atr_series.iloc[box_end]) else 0.0
    last_close = float(main_df["close"].iloc[-1])
    atr_pct = atr_now / last_close if last_close > 0 else 0.02
    pivot_h, pivot_l = _extract_pivots(main_df, atr_now)
    tol = _dynamic_tolerance(atr_pct)
    top_t = _count_touches(pivot_h, main_df["high"], box_top, tol)
    bot_t = _count_touches(pivot_l, main_df["low"], box_bottom, tol)
    print(f"  [4] touch      : top={top_t}, bot={bot_t} (각 ≥{_TOUCH_MIN_TOP}) "
          f"pivot_h={len(pivot_h)}, pivot_l={len(pivot_l)}, tol={tol*100:.1f}% "
          f"{'OK' if top_t >= _TOUCH_MIN_TOP and bot_t >= _TOUCH_MIN_BOTTOM else 'FAIL'}")
    if top_t < _TOUCH_MIN_TOP or bot_t < _TOUCH_MIN_BOTTOM:
        return

    recent_df = df_r.iloc[box_end + 1:]
    threshold = box_top * (1 + BOX_BREAKOUT_BREAK_PCT)
    breakout_mask = recent_df["close"] > threshold
    max_recent = float(recent_df["close"].max())
    print(f"  [5] breakout   : box_top={box_top:.0f}, threshold={threshold:.0f}, "
          f"recent_max={max_recent:.0f} (short={(max_recent-box_top)/box_top*100:+.2f}%) "
          f"{'OK' if breakout_mask.any() else 'FAIL'}")
    if not breakout_mask.any():
        return

    breakout_idx = int(breakout_mask[breakout_mask].index[-1])
    vr = volume_ratio(df_r["volume"])
    cvr = float(vr.iloc[breakout_idx])
    print(f"  [6] volume     : vol_ratio={cvr:.2f} (≥{BOX_BREAKOUT_VOLUME_RATIO}) "
          f"{'OK' if cvr >= BOX_BREAKOUT_VOLUME_RATIO else 'FAIL'}")
    if pd.isna(cvr) or cvr < BOX_BREAKOUT_VOLUME_RATIO:
        return

    print(f"  → PASS")


def main() -> None:
    print(f"=== v3 추적 진단 (PR #38 통과 종목 5건) ===")
    print(f"config: RANGE_PCT={BOX_BREAKOUT_RANGE_PCT}, RECENT_DAYS={BOX_BREAKOUT_RECENT_DAYS}, "
          f"BREAK_PCT={BOX_BREAKOUT_BREAK_PCT}, VOLUME_RATIO={BOX_BREAKOUT_VOLUME_RATIO}")
    print(f"        _MAIN_WINDOW={_MAIN_WINDOW}, _SHORT_COMPRESSION_MAX={_SHORT_COMPRESSION_MAX}")

    for t in TICKERS_TO_TRACE:
        df = _load_daily(t)
        if df.empty:
            print(f"\n=== {t} === no_data")
            continue
        _trace_detailed(t, df)


if __name__ == "__main__":
    main()
