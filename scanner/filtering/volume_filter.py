"""거래량/거래대금 유동성 필터 (CLAUDE.md §7)."""
from __future__ import annotations

import pandas as pd

from scanner.config import (
    LIQUIDITY_LOOKBACK_DAYS,
    MIN_AVG_TRADING_VALUE_KRW,
    MIN_AVG_TRADING_VALUE_USD,
    RECENT_VOLUME_LOOKBACK_DAYS,
)


def passes_volume_filter(
    daily_df: pd.DataFrame,
    market: str,
) -> tuple[bool, dict]:
    """유동성 필터 통과 여부를 반환한다.

    두 가지 조건을 모두 충족해야 True:
    1. 직전 20일 일평균 거래대금 ≥ 임계값 (KR: 50억원, US: 5천만USD)
    2. 최근 5일 거래량 평균 > 직전 20일 거래량 평균

    거래대금(value) 컬럼이 없거나 NaN이면 Typical Price × volume 으로 대체한다.

    Args:
        daily_df: 일봉 OHLCV DataFrame. value 컬럼 선택적.
        market  : "KR" 또는 "US".

    Returns:
        (passed, details) 튜플.
        details 키: avg_value, threshold, ok_value, recent_vol, base_vol, ok_volume_trend.
    """
    m = market.upper()
    threshold = MIN_AVG_TRADING_VALUE_KRW if m == "KR" else MIN_AVG_TRADING_VALUE_USD

    # ── 거래대금 계산 ─────────────────────────────────────────────
    value_series = _get_value_series(daily_df)
    lookback = min(LIQUIDITY_LOOKBACK_DAYS, len(value_series))
    avg_value = float(value_series.iloc[-lookback:].mean()) if lookback > 0 else 0.0
    ok_value = avg_value >= threshold

    # ── 거래량 모멘텀 계산 ────────────────────────────────────────
    if "volume" in daily_df.columns and len(daily_df) >= RECENT_VOLUME_LOOKBACK_DAYS + 1:
        vol = daily_df["volume"]
        recent_vol = float(vol.iloc[-RECENT_VOLUME_LOOKBACK_DAYS:].mean())
        base_lookback = min(LIQUIDITY_LOOKBACK_DAYS, len(vol))
        base_vol = float(vol.iloc[-base_lookback:].mean())
        ok_volume_trend = recent_vol > base_vol
    else:
        recent_vol = 0.0
        base_vol = 0.0
        ok_volume_trend = False

    passed = ok_value and ok_volume_trend

    details: dict = {
        "avg_value": round(avg_value, 0),
        "threshold": threshold,
        "ok_value": ok_value,
        "recent_vol": round(recent_vol, 0),
        "base_vol": round(base_vol, 0),
        "ok_volume_trend": ok_volume_trend,
    }
    return passed, details


def _get_value_series(daily_df: pd.DataFrame) -> pd.Series:
    """거래대금 시리즈를 반환한다.

    value 컬럼이 있고 NaN이 아닌 행이 충분하면 그대로 사용.
    그렇지 않으면 Typical Price × volume 으로 계산한다.
    """
    if "value" in daily_df.columns:
        v = daily_df["value"].dropna()
        if len(v) >= LIQUIDITY_LOOKBACK_DAYS // 2:
            return daily_df["value"].fillna(0.0)

    # Typical Price fallback
    required = {"high", "low", "close", "volume"}
    if required.issubset(daily_df.columns):
        tp = (daily_df["high"] + daily_df["low"] + daily_df["close"]) / 3.0
        return tp * daily_df["volume"]

    # 마지막 수단: close × volume
    if "close" in daily_df.columns and "volume" in daily_df.columns:
        return daily_df["close"] * daily_df["volume"]

    return pd.Series(dtype=float)
