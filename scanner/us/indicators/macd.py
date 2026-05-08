"""MACD (Moving Average Convergence Divergence) 계산."""
from __future__ import annotations

import pandas as pd


def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD 라인, 시그널 라인, 히스토그램을 반환한다.

    MACD line   = EMA(fast) − EMA(slow)
    Signal line = EMA(MACD line, signal)
    Histogram   = MACD line − Signal line

    Args:
        close : 종가 시계열.
        fast  : 단기 EMA span (기본 12).
        slow  : 장기 EMA span (기본 26).
        signal: 시그널 EMA span (기본 9).

    Returns:
        (macd_line, signal_line, histogram) 세 시리즈의 튜플.
    """
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def is_bullish_cross(
    macd_series: pd.Series,
    signal_series: pd.Series,
    lookback: int = 5,
) -> bool:
    """최근 lookback 봉 안에 MACD 골든크로스(상향 돌파)가 있는지 판정한다.

    골든크로스 조건: 이전 봉에서 macd <= signal 이었다가
    현재 봉에서 macd > signal 로 전환.

    Args:
        macd_series  : MACD 라인 시계열.
        signal_series: 시그널 라인 시계열.
        lookback     : 탐색 봉 수 (기본 5).

    Returns:
        lookback 구간 내 골든크로스가 있으면 True.
    """
    if len(macd_series) < 2:
        return False

    window = min(lookback, len(macd_series))
    m = macd_series.iloc[-window:]
    s = signal_series.iloc[-window:]

    for i in range(1, len(m)):
        prev_below = m.iloc[i - 1] <= s.iloc[i - 1]
        curr_above = m.iloc[i] > s.iloc[i]
        if prev_below and curr_above:
            return True
    return False
