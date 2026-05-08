"""재무 필터 (CLAUDE.md §8 — 시가총액만)."""
from __future__ import annotations

from scanner.config import (
    MIN_MARKET_CAP_KRW,
    MIN_MARKET_CAP_USD,
)


def passes_fundamental_filter(
    ticker: str,
    market: str,
    fundamentals: dict[str, float | None],
) -> tuple[bool, dict]:
    """재무 필터 (시가총액 기준) 통과 여부를 반환한다.

    KR 기준: 시가총액 ≥ 1,000억원
    US 기준: 시가총액 ≥ 10억 USD

    Args:
        ticker      : 종목 코드 (로깅용).
        market      : "KR" 또는 "US".
        fundamentals: {'market_cap'} 키를 가진 딕셔너리.
                      ``market_cap`` 이 None 이면 미충족.

    Returns:
        (passed, details) 튜플.
        details 키: ok_market_cap, market_cap, passed.
    """
    m = market.upper()
    market_cap = fundamentals.get("market_cap")

    threshold = MIN_MARKET_CAP_KRW if m == "KR" else MIN_MARKET_CAP_USD
    ok_cap = market_cap is not None and float(market_cap) >= threshold
    passed = ok_cap

    details: dict = {
        "ok_market_cap": ok_cap,
        "market_cap": market_cap,
        "passed": passed,
    }
    return passed, details
