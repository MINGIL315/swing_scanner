"""박스권 돌파 (box_breakout) detect 단계별 실패 원인 분석.

KOSPI200 200종목 일봉을 모두 detect 로직에 흘려 보내, 어느 단계에서 None 으로
떨어지는지 집계한다.

단계:
  1. 데이터 부족 (len < 64)
  2. _find_best_box 단계
     - 윈도우 [30, 45, 60] 각각의 통과/실패
     - 실패 원인: 데이터 부족 / range_pct > 10% / 돌파 없음
  3. 돌파일 거래량 비율 < 1.5

추가:
  - 통과한 종목의 box_top / range_pct / vol_ratio 분포
  - "거의 통과" 종목 (box 는 찾았으나 거래량 미달) 샘플 출력 — 임계값 조정 sense.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import select

from scanner.config import (
    BOX_BREAKOUT_BREAK_PCT,
    BOX_BREAKOUT_MAX_DAYS,
    BOX_BREAKOUT_RANGE_PCT,
    BOX_BREAKOUT_RECENT_DAYS,
    BOX_BREAKOUT_VOLUME_RATIO,
)
from scanner.db.models import OHLCVDaily, Universe
from scanner.db.session import get_session
from scanner.kr.indicators.volume import volume_ratio
from scanner.kr.patterns.box_breakout import _BOX_WINDOWS, _find_best_box


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


def _kr_tickers() -> list[str]:
    with get_session() as session:
        return [
            t for (t,) in session.execute(
                select(Universe.ticker)
                .where(Universe.market == "KR")
                .where(Universe.is_active.is_(True))
            ).all()
        ]


def _diag_one(ticker: str, df: pd.DataFrame) -> dict:
    """단일 종목 detect 단계별 진단 결과 dict 반환."""
    info: dict = {
        "ticker": ticker,
        "rows": len(df),
        "stage": None,         # 어디서 빠졌는지
        "best_window": None,
        "box_top": None,
        "box_bottom": None,
        "range_pct": None,
        "vol_ratio_at_break": None,
        "window_fails": {},    # window → reason
    }

    min_rows = BOX_BREAKOUT_MAX_DAYS + BOX_BREAKOUT_RECENT_DAYS + 1
    if len(df) < min_rows:
        info["stage"] = "data_insufficient"
        return info

    df_r = df.reset_index(drop=True)

    # 윈도우별 fail 사유 집계 (_find_best_box 의 내부 로직 재현)
    n = len(df_r)
    for window in _BOX_WINDOWS:
        if n < window + BOX_BREAKOUT_RECENT_DAYS + 1:
            info["window_fails"][window] = "rows_insufficient"
            continue
        box_end = n - BOX_BREAKOUT_RECENT_DAYS - 1
        box_start = box_end - window
        box_df = df_r.iloc[box_start:box_end + 1]
        mean_price = float(box_df["close"].mean())
        if mean_price == 0:
            info["window_fails"][window] = "zero_price"
            continue

        box_top = float(box_df["high"].max())
        box_bottom = float(box_df["low"].min())
        range_pct = (box_top - box_bottom) / mean_price

        if range_pct > BOX_BREAKOUT_RANGE_PCT:
            info["window_fails"][window] = f"range_too_wide ({range_pct*100:.1f}%)"
            continue

        recent_df = df_r.iloc[box_end + 1:]
        breakout_threshold = box_top * (1 + BOX_BREAKOUT_BREAK_PCT)
        breakout_mask = recent_df["close"] > breakout_threshold
        if not breakout_mask.any():
            recent_max_close = float(recent_df["close"].max())
            short_pct = (recent_max_close - box_top) / box_top * 100
            info["window_fails"][window] = (
                f"no_breakout (max_close={recent_max_close:.0f}, "
                f"need>{breakout_threshold:.0f}, short={short_pct:+.2f}%)"
            )
            continue

        info["window_fails"][window] = "OK"

    box = _find_best_box(df_r)
    if box is None:
        info["stage"] = "no_valid_box"
        return info

    info["best_window"] = box.window_days
    info["box_top"] = box.box_top
    info["box_bottom"] = box.box_bottom
    info["range_pct"] = box.range_pct

    vr_series = volume_ratio(df_r["volume"])
    cross_vr = float(vr_series.iloc[box.breakout_idx])
    info["vol_ratio_at_break"] = cross_vr

    if pd.isna(cross_vr) or cross_vr < BOX_BREAKOUT_VOLUME_RATIO:
        info["stage"] = "volume_insufficient"
        return info

    info["stage"] = "PASS"
    return info


def main() -> None:
    tickers = _kr_tickers()
    print(f"=== box_breakout 진단 (KOSPI200 {len(tickers)}종목) ===\n")

    print("config:")
    print(f"  BOX_BREAKOUT_MIN/MAX_DAYS = 30 / {BOX_BREAKOUT_MAX_DAYS}")
    print(f"  BOX_BREAKOUT_RANGE_PCT     = {BOX_BREAKOUT_RANGE_PCT*100:.0f}%")
    print(f"  BOX_BREAKOUT_BREAK_PCT     = {BOX_BREAKOUT_BREAK_PCT*100:.0f}%")
    print(f"  BOX_BREAKOUT_RECENT_DAYS   = {BOX_BREAKOUT_RECENT_DAYS}")
    print(f"  BOX_BREAKOUT_VOLUME_RATIO  = {BOX_BREAKOUT_VOLUME_RATIO}")
    print(f"  _BOX_WINDOWS               = {_BOX_WINDOWS}\n")

    results: list[dict] = []
    for t in tickers:
        df = _load_daily(t)
        if df.empty:
            results.append({"ticker": t, "stage": "no_data", "rows": 0, "window_fails": {}})
            continue
        results.append(_diag_one(t, df))

    stage_counter = Counter(r["stage"] for r in results)
    print(f"단계별 결과 분포:")
    for stage, cnt in stage_counter.most_common():
        print(f"  {stage:30s} {cnt}")
    print()

    # _find_best_box 단계의 윈도우별 fail 사유 분포
    print("윈도우별 fail 사유 (_find_best_box 단계, no_valid_box 종목 대상):")
    for window in _BOX_WINDOWS:
        reason_counter: Counter[str] = Counter()
        for r in results:
            if r["stage"] != "no_valid_box":
                continue
            reason = r["window_fails"].get(window, "—")
            # range_too_wide 는 % 빼고 buckets
            if reason.startswith("range_too_wide"):
                reason = "range_too_wide"
            elif reason.startswith("no_breakout"):
                reason = "no_breakout"
            reason_counter[reason] += 1
        print(f"  window={window}: {dict(reason_counter.most_common())}")
    print()

    # range_pct 분포 (no_valid_box 중 가장 작은 윈도우의 range)
    print("no_valid_box 종목들의 윈도우별 range_pct 분포 (range_too_wide 만):")
    for window in _BOX_WINDOWS:
        ranges = []
        for r in results:
            if r["stage"] != "no_valid_box":
                continue
            reason = r["window_fails"].get(window, "")
            if reason.startswith("range_too_wide"):
                pct_str = reason.split("(")[1].rstrip("%)")
                ranges.append(float(pct_str))
        if ranges:
            ranges.sort()
            n = len(ranges)
            print(
                f"  window={window} ({n}개): "
                f"min={min(ranges):.1f}%  median={ranges[n//2]:.1f}%  max={max(ranges):.1f}%  "
                f"p25={ranges[n//4]:.1f}%  p75={ranges[3*n//4]:.1f}%"
            )

    # 통과한 종목 정보
    pass_results = [r for r in results if r["stage"] == "PASS"]
    near_pass = [r for r in results if r["stage"] == "volume_insufficient"]
    print(f"\nPASS: {len(pass_results)}건")
    for r in pass_results[:5]:
        print(f"  {r['ticker']}  win={r['best_window']}  range={r['range_pct']*100:.1f}%  "
              f"box_top={r['box_top']:.0f}  vol_ratio={r['vol_ratio_at_break']:.2f}")

    print(f"\n거래량만 미달: {len(near_pass)}건")
    for r in near_pass[:10]:
        print(f"  {r['ticker']}  win={r['best_window']}  range={r['range_pct']*100:.1f}%  "
              f"box_top={r['box_top']:.0f}  vol_ratio={r['vol_ratio_at_break']:.2f} (need ≥1.5)")


if __name__ == "__main__":
    main()
