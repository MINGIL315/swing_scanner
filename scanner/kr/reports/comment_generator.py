"""AI 코멘트 자동 생성기.

패턴 분석 결과를 바탕으로 4단계 텍스트 코멘트를 생성한다:
1. 큰 추세  2. 패턴 분석  3. 진입 추천  4. 리스크 경고
"""
from __future__ import annotations

from typing import Any


_TREND_TEXT: dict[str, str] = {
    "uptrend": (
        "주봉 기준 상승 추세가 유지되고 있습니다. 큰 흐름이 매수에 우호적입니다."
    ),
    "sideways": (
        "주봉 기준 횡보 구간에 위치합니다. "
        "방향성이 확정되기 전까지 보수적으로 접근하세요."
    ),
    "downtrend": (
        "주봉 기준 하락 추세입니다. "
        "일봉 반등은 단기 노이즈일 수 있으므로 신중히 판단하세요."
    ),
}

_PATTERN_TEXT: dict[str, str] = {
    "double_bottom": (
        "최근 60일 내 두 개의 유사한 저점이 형성되어 쌍바닥 패턴이 완성되었습니다. "
        "목선 돌파는 추세 전환의 신호로, 매수세가 유입되고 있음을 나타냅니다."
    ),
    "golden_cross": (
        "20일 이동평균선이 60일 이동평균선을 최근 5일 이내에 상향 돌파했습니다. "
        "거래량이 동반 증가한 골든크로스는 중기 상승 전환의 신뢰도 높은 신호입니다."
    ),
    "box_breakout": (
        "30~60일간의 박스권 횡보 이후 상단을 돌파했습니다. "
        "긴 에너지 축적 이후의 돌파는 새로운 상승 국면의 시작을 의미할 수 있습니다."
    ),
    "pullback": (
        "상승 추세 중 단기 눌림목에서 반등 조짐이 포착됩니다. "
        "20일선 또는 60일선 부근에서 지지를 받으며 양봉을 형성해 "
        "재상승 가능성을 높이고 있습니다."
    ),
}

_ENTRY_TEMPLATE = (
    "진입가 {entry:.2f} 기준으로, 손절가 {stop:.2f}(리스크 {risk:.1f}%), "
    "목표가 {target:.2f}(수익 {reward:.1f}%, R:R 1:{rr:.1f})를 권장합니다. "
    "시가 또는 눌림 재확인 후 분할 진입을 검토하세요."
)

_ENTRY_FALLBACK = (
    "진입·손절·목표 가격을 확인하고 리스크 비율에 맞춰 포지션 크기를 결정하세요."
)

_RISK_TEXT: dict[str, str] = {
    "uptrend": (
        "주봉 추세가 우호적이나, 실적·금리·환율 등 외부 이벤트에 따른 "
        "돌발 하락에 항상 유의하세요."
    ),
    "sideways": (
        "횡보 구간이므로 돌파 실패 시 손절을 엄격히 지킵니다. "
        "추가 확인 없이 무리한 비중 확대는 자제하세요."
    ),
    "downtrend": (
        "하락 추세 속 반등 시도이므로 매수에 매우 신중해야 합니다. "
        "추세 전환을 확인한 후 진입하는 것을 권장합니다."
    ),
}


def generate_comment(row: dict[str, Any]) -> list[dict[str, str]]:
    """스캔 결과 dict 로부터 4단계 AI 코멘트를 생성한다.

    Args:
        row: _attach_market() 으로 생성된 스캔 결과 dict.

    Returns:
        ``[{label, text}, ...]`` 형태의 4-phase 리스트.
    """
    trend = row.get("trend_weekly") or "sideways"
    pattern = row.get("pattern_name", "")

    entry = row.get("entry_price")
    stop = row.get("stop_loss")
    target = row.get("target_price")
    rr = row.get("risk_reward_ratio")

    if entry and stop and target and rr and entry > 0:
        risk_pct = (entry - stop) / entry * 100
        reward_pct = (target - entry) / entry * 100
        entry_text = _ENTRY_TEMPLATE.format(
            entry=entry, stop=stop, target=target,
            risk=risk_pct, reward=reward_pct, rr=rr,
        )
    else:
        entry_text = _ENTRY_FALLBACK

    return [
        {"label": "큰 추세",    "text": _TREND_TEXT.get(trend, _TREND_TEXT["sideways"])},
        {"label": "패턴 분석",  "text": _PATTERN_TEXT.get(pattern, "패턴 상세 정보를 확인하세요.")},
        {"label": "진입 추천",  "text": entry_text},
        {"label": "리스크 경고","text": _RISK_TEXT.get(trend, _RISK_TEXT["sideways"])},
    ]


__all__ = ["generate_comment"]
