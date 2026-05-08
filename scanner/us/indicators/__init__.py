"""기술 지표 패키지.

enrich_dataframe() 하나만 호출하면 일봉·주봉·분봉 DataFrame에
MA, RSI, MACD, 거래량 비율 컬럼이 모두 추가된다.
"""
from __future__ import annotations

from typing import Literal

import pandas as pd

from scanner.us.indicators.macd import is_bullish_cross, macd
from scanner.us.indicators.moving_average import (
    add_moving_averages,
    is_bearish_alignment,
    is_bullish_alignment,
    sma,
    ema,
)
from scanner.us.indicators.rsi import is_overbought, is_oversold, rsi
from scanner.us.indicators.volume import avg_value, is_volume_surge, value_ratio, volume_ratio

Timeframe = Literal["daily", "weekly", "intraday"]


def enrich_dataframe(
    df: pd.DataFrame,
    timeframe: Timeframe = "daily",
) -> pd.DataFrame:
    """OHLCV DataFrame에 모든 기술 지표 컬럼을 한 번에 추가한다.

    timeframe에 따라 계산 대상 지표를 조정한다:
        daily / intraday : MA(5,20,60,120) + RSI(14) + MACD(12,26,9) + volume_ratio(20)
        weekly           : MA(5,20,60) + RSI(14) + volume_ratio(20)
                           (주봉은 MACD 생략 — 데이터 행 수 부족 시 NaN 범람 방지)

    추가되는 컬럼:
        ma_5, ma_20, ma_60, [ma_120]
        rsi_14
        [macd_line, macd_signal, macd_hist]
        volume_ratio_20
        [value_ratio_20, avg_value_20]  ← value 컬럼이 있을 때만

    Args:
        df       : open/high/low/close/volume 컬럼을 가진 DataFrame.
        timeframe: 'daily', 'weekly', 'intraday' 중 하나.

    Returns:
        지표 컬럼이 추가된 복사본.
    """
    result = df.copy()
    close = result["close"]

    # ── 이동평균선 ──────────────────────────────────────────────
    if timeframe == "weekly":
        result = add_moving_averages(result, periods=[5, 20, 60])
    else:
        result = add_moving_averages(result, periods=[5, 20, 60, 120])

    # ── RSI ────────────────────────────────────────────────────
    result["rsi_14"] = rsi(close, period=14)

    # ── MACD (daily / intraday 전용) ───────────────────────────
    if timeframe != "weekly":
        macd_line, signal_line, histogram = macd(close)
        result["macd_line"] = macd_line
        result["macd_signal"] = signal_line
        result["macd_hist"] = histogram

    # ── 거래량 비율 ─────────────────────────────────────────────
    if "volume" in result.columns:
        result["volume_ratio_20"] = volume_ratio(result["volume"], period=20)

    # ── 거래대금 비율 / 평균 (value 컬럼 있을 때만) ──────────────
    if "value" in result.columns:
        result["value_ratio_20"] = value_ratio(result["value"], period=20)
        result["avg_value_20"] = avg_value(result["value"], period=20)

    return result


__all__ = [
    # moving_average
    "sma",
    "ema",
    "add_moving_averages",
    "is_bullish_alignment",
    "is_bearish_alignment",
    # rsi
    "rsi",
    "is_oversold",
    "is_overbought",
    # macd
    "macd",
    "is_bullish_cross",
    # volume
    "volume_ratio",
    "value_ratio",
    "avg_value",
    "is_volume_surge",
    # 통합
    "enrich_dataframe",
]
