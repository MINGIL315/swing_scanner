"""거래량 모멘텀 필터 (CLAUDE.md §7).

조건: 최근 5일 거래량 평균 > 직전 20일 거래량 평균.
(자금 유입/관심 증가 신호 — 차트 패턴 신호의 진정성 확인용)

옛 일평균 거래대금 컷(KR 50억원, US 5천만 USD)은 폐기되었다 (KOSPI200
우량주 단계에서 사실상 모든 종목이 통과해 의미 작음 — 2026-05-09).
거래대금 데이터(``OHLCVDaily.value``) 자체는 계속 적재되며 KOSPI 외 일반/
KOSDAQ 도입 시 재활성화 검토 가능.
"""
from __future__ import annotations

import pandas as pd

from scanner.config import (
    LIQUIDITY_LOOKBACK_DAYS,
    RECENT_VOLUME_LOOKBACK_DAYS,
)


def passes_volume_filter(
    daily_df: pd.DataFrame,
    market: str,
) -> tuple[bool, dict]:
    """거래량 모멘텀 필터 통과 여부를 반환한다.

    Args:
        daily_df: 일봉 OHLCV DataFrame. ``volume`` 컬럼 필수.
        market  : "KR" 또는 "US" (현재 동일 동작 — 시그니처 호환성 유지).

    Returns:
        (passed, details) 튜플.
        details 키: recent_vol, base_vol, ok_volume_trend, passed.
    """
    if "volume" not in daily_df.columns or len(daily_df) < RECENT_VOLUME_LOOKBACK_DAYS + 1:
        return False, {
            "recent_vol": 0.0,
            "base_vol": 0.0,
            "ok_volume_trend": False,
            "passed": False,
        }

    vol = daily_df["volume"]
    recent_vol = float(vol.iloc[-RECENT_VOLUME_LOOKBACK_DAYS:].mean())
    base_lookback = min(LIQUIDITY_LOOKBACK_DAYS, len(vol))
    base_vol = float(vol.iloc[-base_lookback:].mean())
    ok_volume_trend = recent_vol > base_vol

    return ok_volume_trend, {
        "recent_vol": round(recent_vol, 0),
        "base_vol": round(base_vol, 0),
        "ok_volume_trend": ok_volume_trend,
        "passed": ok_volume_trend,
    }
