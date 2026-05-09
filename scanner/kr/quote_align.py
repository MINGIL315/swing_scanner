"""한국 주식 호가 단위(price tick) 정렬.

KRX 정규시장(코스피/코스닥 통합) 호가 단위표에 맞춰 가격을 정렬한다.
2023-01-25 부터 코스피·코스닥 호가 단위가 통합되어 동일.

호가 단위표:
    1,000원 미만        → 1원
    1,000원 ~ 5,000원   → 5원
    5,000원 ~ 20,000원  → 10원
    20,000원 ~ 50,000원 → 50원
    50,000원 ~ 200,000원 → 100원
    200,000원 ~ 500,000원 → 500원
    500,000원 이상       → 1,000원

(상한선은 미만 — 1,000원은 5원 단위, 5,000원은 10원 단위 등.)

손절가/목표가 등 분석 결과 가격이 호가에 없는 단위로 출력되어 사용자가
주문 불가능한 가격을 받지 않도록 출력 직전 ``align_to_tick`` 으로 정렬한다.
"""
from __future__ import annotations


# (상한값, 호가 단위) — price < 상한값 이면 해당 호가 단위 적용
_TICK_TABLE: list[tuple[float, int]] = [
    (1_000, 1),
    (5_000, 5),
    (20_000, 10),
    (50_000, 50),
    (200_000, 100),
    (500_000, 500),
    (float("inf"), 1_000),
]


def get_tick_size(price: float) -> int:
    """가격에 해당하는 호가 단위(원)를 반환한다.

    Args:
        price: 종목 가격.

    Returns:
        호가 단위(1, 5, 10, 50, 100, 500, 1000 중 하나).
    """
    for upper, tick in _TICK_TABLE:
        if price < upper:
            return tick
    return 1_000  # unreachable (inf 가 마지막)


def align_to_tick(price: float) -> float:
    """가격을 가장 가까운 호가 단위로 정렬(반올림)한다.

    .5 경계는 half-up (위로) 처리한다 — 한국 호가 관행에 부합.

    Args:
        price: 정렬할 가격. 음수/0 은 그대로 반환.

    Returns:
        호가 단위로 정렬된 정수 가격 (float 형).

    예시:
        align_to_tick(97_048.5)  → 97_000.0   # 100원 단위
        align_to_tick(231_127)    → 231_000.0  # 500원 단위
        align_to_tick(12_345)     → 12_350.0   # 10원 단위 (half-up)
    """
    if price <= 0:
        return float(price)
    tick = get_tick_size(price)
    # half-up: int(x + 0.5) (양수 가격에서만 사용)
    return float(int(price / tick + 0.5) * tick)
