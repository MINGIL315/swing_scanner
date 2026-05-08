"""재무 필터 단위 테스트 (시가총액 단일 조건)."""
from __future__ import annotations

from scanner.config import (
    MIN_MARKET_CAP_KRW,
    MIN_MARKET_CAP_USD,
)
from scanner.us.filtering.fundamental_filter import passes_fundamental_filter


# ---------------------------------------------------------------------------
# KR 필터 테스트
# ---------------------------------------------------------------------------


class TestFundamentalFilterKR:
    _valid = {"market_cap": MIN_MARKET_CAP_KRW + 1e10}

    def test_passes_all_valid(self) -> None:
        passed, _ = passes_fundamental_filter("005930", "KR", self._valid)
        assert passed is True

    def test_fails_low_market_cap(self) -> None:
        f = {"market_cap": MIN_MARKET_CAP_KRW * 0.5}
        passed, details = passes_fundamental_filter("TEST", "KR", f)
        assert passed is False
        assert details["ok_market_cap"] is False

    def test_fails_none_market_cap(self) -> None:
        f = {"market_cap": None}
        passed, _ = passes_fundamental_filter("TEST", "KR", f)
        assert passed is False

    def test_details_contains_kr_keys(self) -> None:
        _, details = passes_fundamental_filter("TEST", "KR", self._valid)
        for key in ("ok_market_cap", "market_cap", "passed"):
            assert key in details
        # 폐기된 필터 키들이 없어야
        for key in ("ok_per", "ok_debt_ratio", "debt_ratio", "per"):
            assert key not in details

    def test_exact_market_cap_boundary(self) -> None:
        """시가총액이 정확히 임계값이면 통과."""
        f = {"market_cap": float(MIN_MARKET_CAP_KRW)}
        _, details = passes_fundamental_filter("TEST", "KR", f)
        assert details["ok_market_cap"] is True

    def test_case_insensitive_market(self) -> None:
        passed, _ = passes_fundamental_filter("TEST", "kr", self._valid)
        assert passed is True


# ---------------------------------------------------------------------------
# US 필터 테스트
# ---------------------------------------------------------------------------


class TestFundamentalFilterUS:
    _valid = {"market_cap": MIN_MARKET_CAP_USD + 1e8}

    def test_passes_all_valid(self) -> None:
        passed, _ = passes_fundamental_filter("AAPL", "US", self._valid)
        assert passed is True

    def test_fails_low_market_cap(self) -> None:
        f = {"market_cap": MIN_MARKET_CAP_USD * 0.5}
        passed, details = passes_fundamental_filter("TEST", "US", f)
        assert passed is False
        assert details["ok_market_cap"] is False

    def test_details_contains_us_keys(self) -> None:
        _, details = passes_fundamental_filter("TEST", "US", self._valid)
        for key in ("ok_market_cap", "market_cap", "passed"):
            assert key in details
        for key in ("ok_per", "ok_debt_ratio", "debt_ratio", "per"):
            assert key not in details
