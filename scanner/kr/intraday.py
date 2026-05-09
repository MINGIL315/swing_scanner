"""1분봉 → N분봉(60분 / 4시간) 합성 유틸.

KIS 가 1분봉만 제공하므로 60분봉 / 4시간봉은 분석 시점에 합성한다.

CLAUDE.md §1 의 멀티 타임프레임 정의:
    - 4시간봉 = 60분봉 4개 = 진입 타이밍 프레임 (거래량·캔들·RSI 다이버전스)

집계 규칙 (OHLC 표준):
    open   = 첫 1분봉 open
    high   = 구간 내 최대 high
    low    = 구간 내 최소 low
    close  = 마지막 1분봉 close
    volume = 구간 내 volume 합

부분 봉 (영업시간 끝의 마지막 60분 미만 / 4시간 미만 그룹) 처리 옵션:
    drop_partial=True   → 완전한 봉만 남김 (분석 안정성)
    drop_partial=False  → 부분 봉 포함 (실시간 표시용)

한국 정규시장 영업시간(09:00~15:30, 점심 휴식 X) 기준이며
``origin='start_day'`` 사용 — 09:00 부터 정시 단위로 그룹핑.
"""
from __future__ import annotations

import pandas as pd


_AGG = {
    "open": "first",
    "high": "max",
    "low": "min",
    "close": "last",
    "volume": "sum",
}


def resample_to_minutes(
    df_1min: pd.DataFrame,
    rule: str = "60min",
    drop_partial: bool = True,
) -> pd.DataFrame:
    """1분봉 DataFrame 을 N분봉으로 합성한다.

    Args:
        df_1min      : columns 에 ``[ticker, datetime, open, high, low, close, volume]``
                       포함. ``datetime`` 은 시간 정순 정렬되어 있어야 한다.
        rule         : pandas resample rule. 권장값:
                       - ``"60min"`` (60분봉)
                       - ``"4h"`` 또는 ``"240min"`` (4시간봉)
        drop_partial : True 면 완전한 봉만 (1분봉 갯수가 rule 의 분량을 채운 그룹).
                       False 면 부분 봉 포함.

    Returns:
        columns = [ticker, datetime, open, high, low, close, volume]
        ``datetime`` 은 각 그룹의 시작 시각 (예: 60min 의 09:00 봉 = 09:00:00).
        빈 결과 시 빈 DataFrame.

    예시:
        1분봉 09:00~15:30 (390개) → resample_to_minutes(rule='60min', drop_partial=False)
            = 7개 60분봉 (09/10/11/12/13/14/15시 시작, 마지막은 30분 부분)
        drop_partial=True 면 6개 (15시 부분 봉 drop).
    """
    if df_1min is None or df_1min.empty:
        return pd.DataFrame(
            columns=["ticker", "datetime", "open", "high", "low", "close", "volume"]
        )

    df = df_1min.copy()
    df["datetime"] = pd.to_datetime(df["datetime"])

    ticker = df["ticker"].iloc[0] if "ticker" in df.columns and len(df) else None

    grouped = (
        df.set_index("datetime")[list(_AGG.keys())]
        .resample(rule, origin="start_day", label="left", closed="left")
        .agg(_AGG)
    )

    if drop_partial:
        # 부분 봉 판정 — volume 0 인 빈 그룹 또는 데이터 양이 rule 분량 미만
        # rule 분량 산출 (간단화): 60min → 60, 4h → 240
        bar_minutes = _rule_minutes(rule)
        if bar_minutes:
            counts = (
                df.set_index("datetime")
                .resample(rule, origin="start_day", label="left", closed="left")
                .size()
            )
            full_index = counts[counts >= bar_minutes].index
            grouped = grouped.loc[grouped.index.isin(full_index)]

    grouped = grouped.dropna(how="all").reset_index()

    if ticker is not None:
        grouped.insert(0, "ticker", ticker)

    return grouped


def resample_to_4h(df_1min: pd.DataFrame, drop_partial: bool = True) -> pd.DataFrame:
    """1분봉 → 4시간봉 (CLAUDE.md §1 의 진입 타이밍 프레임).

    한국 정규시장 6.5h 영업시간 → 4시간봉 1~2개/일. 부분 봉 drop 권장.
    """
    return resample_to_minutes(df_1min, rule="4h", drop_partial=drop_partial)


def resample_to_60min(df_1min: pd.DataFrame, drop_partial: bool = True) -> pd.DataFrame:
    """1분봉 → 60분봉 (4시간봉의 원천 단위)."""
    return resample_to_minutes(df_1min, rule="60min", drop_partial=drop_partial)


def _rule_minutes(rule: str) -> int | None:
    """``"60min"``, ``"4h"`` 같은 rule 을 분 단위 정수로 변환. 인식 불가 시 None."""
    rule_lower = rule.lower().strip()
    if rule_lower.endswith("min"):
        try:
            return int(rule_lower[:-3])
        except ValueError:
            return None
    if rule_lower.endswith("h"):
        try:
            return int(rule_lower[:-1]) * 60
        except ValueError:
            return None
    return None
