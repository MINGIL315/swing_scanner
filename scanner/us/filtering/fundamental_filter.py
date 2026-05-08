"""재무 필터 (CLAUDE.md §8)."""
from __future__ import annotations

from scanner.config import (
    MAX_DEBT_RATIO_KR,
    MIN_MARKET_CAP_KRW,
    MIN_MARKET_CAP_USD,
    MIN_PER,
)


def passes_fundamental_filter(
    ticker: str,
    market: str,
    fundamentals: dict[str, float | None],
) -> tuple[bool, dict]:
    """재무 필터 통과 여부를 반환한다.

    KR 기준:
        - 시가총액 ≥ 1,000억원
        - PER > 0 (적자 종목 제외)
        - 부채비율 < 200%

    US 기준:
        - 시가총액 ≥ 10억 USD
        - PER > 0

    Args:
        ticker      : 종목 코드 (로깅용).
        market      : "KR" 또는 "US".
        fundamentals: {'market_cap', 'per', 'debt_ratio'} 키를 가진 딕셔너리.
                      값이 None이면 해당 조건은 미충족으로 처리한다.

    Returns:
        (passed, details) 튜플.
        details 키: ok_market_cap, ok_per, ok_debt_ratio(KR만), passed.
    """
    m = market.upper()
    market_cap = fundamentals.get("market_cap")
    per = fundamentals.get("per")
    debt_ratio = fundamentals.get("debt_ratio")

    if m == "KR":
        ok_cap = market_cap is not None and float(market_cap) >= MIN_MARKET_CAP_KRW
        ok_per = per is not None and float(per) > MIN_PER
        ok_debt = debt_ratio is None or float(debt_ratio) < MAX_DEBT_RATIO_KR
        passed = ok_cap and ok_per and ok_debt
        details: dict = {
            "ok_market_cap": ok_cap,
            "ok_per": ok_per,
            "ok_debt_ratio": ok_debt,
            "market_cap": market_cap,
            "per": per,
            "debt_ratio": debt_ratio,
            "passed": passed,
        }
    else:  # US (및 기타)
        ok_cap = market_cap is not None and float(market_cap) >= MIN_MARKET_CAP_USD
        ok_per = per is not None and float(per) > MIN_PER
        passed = ok_cap and ok_per
        details = {
            "ok_market_cap": ok_cap,
            "ok_per": ok_per,
            "market_cap": market_cap,
            "per": per,
            "passed": passed,
        }

    return passed, details
