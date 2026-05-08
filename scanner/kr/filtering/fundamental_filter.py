"""재무 필터 (CLAUDE.md §8 — 시가총액 + KR 부채비율)."""
from __future__ import annotations

from scanner.config import (
    MAX_DEBT_RATIO_KR,
    MIN_MARKET_CAP_KRW,
    MIN_MARKET_CAP_USD,
)


def passes_fundamental_filter(
    ticker: str,
    market: str,
    fundamentals: dict[str, float | None],
) -> tuple[bool, dict]:
    """재무 필터 통과 여부를 반환한다.

    KR 기준:
        - 시가총액 ≥ 1,000억원
        - 부채비율 < 200% (None 이면 조건 완화 — 통과)

    US 기준:
        - 시가총액 ≥ 10억 USD

    Args:
        ticker      : 종목 코드 (로깅용).
        market      : "KR" 또는 "US".
        fundamentals: {'market_cap', 'debt_ratio'} 키를 가진 딕셔너리.
                      값이 None이면 해당 조건은 미충족으로 처리한다 (debt_ratio 는 예외).

    Returns:
        (passed, details) 튜플.
        details 키: ok_market_cap, ok_debt_ratio(KR만), passed.
    """
    m = market.upper()
    market_cap = fundamentals.get("market_cap")
    debt_ratio = fundamentals.get("debt_ratio")

    if m == "KR":
        ok_cap = market_cap is not None and float(market_cap) >= MIN_MARKET_CAP_KRW
        ok_debt = debt_ratio is None or float(debt_ratio) < MAX_DEBT_RATIO_KR
        passed = ok_cap and ok_debt
        details: dict = {
            "ok_market_cap": ok_cap,
            "ok_debt_ratio": ok_debt,
            "market_cap": market_cap,
            "debt_ratio": debt_ratio,
            "passed": passed,
        }
    else:  # US (및 기타)
        ok_cap = market_cap is not None and float(market_cap) >= MIN_MARKET_CAP_USD
        passed = ok_cap
        details = {
            "ok_market_cap": ok_cap,
            "market_cap": market_cap,
            "passed": passed,
        }

    return passed, details
