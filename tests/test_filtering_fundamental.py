"""재무 필터 단위 테스트."""
from __future__ import annotations

import pytest

from scanner.config import (
    MAX_DEBT_RATIO_KR,
    MIN_MARKET_CAP_KRW,
    MIN_MARKET_CAP_USD,
    MIN_PER,
)
from scanner.kr.filtering.fundamental_filter import passes_fundamental_filter


# ---------------------------------------------------------------------------
# KR 필터 테스트
# ---------------------------------------------------------------------------

class TestFundamentalFilterKR:
    _valid = {
        "market_cap": MIN_MARKET_CAP_KRW + 1e10,
        "per": 12.5,
        "debt_ratio": 80.0,
    }

    def test_passes_all_valid(self) -> None:
        passed, details = passes_fundamental_filter("005930", "KR", self._valid)
        assert passed is True

    def test_fails_low_market_cap(self) -> None:
        f = {**self._valid, "market_cap": MIN_MARKET_CAP_KRW * 0.5}
        passed, details = passes_fundamental_filter("TEST", "KR", f)
        assert passed is False
        assert details["ok_market_cap"] is False

    def test_fails_negative_per(self) -> None:
        f = {**self._valid, "per": -5.0}
        passed, details = passes_fundamental_filter("TEST", "KR", f)
        assert passed is False
        assert details["ok_per"] is False

    def test_fails_zero_per(self) -> None:
        f = {**self._valid, "per": 0.0}
        passed, details = passes_fundamental_filter("TEST", "KR", f)
        assert passed is False
        assert details["ok_per"] is False

    def test_fails_none_per(self) -> None:
        f = {**self._valid, "per": None}
        passed, details = passes_fundamental_filter("TEST", "KR", f)
        assert passed is False
        assert details["ok_per"] is False

    def test_fails_high_debt_ratio(self) -> None:
        f = {**self._valid, "debt_ratio": MAX_DEBT_RATIO_KR + 1.0}
        passed, details = passes_fundamental_filter("TEST", "KR", f)
        assert passed is False
        assert details["ok_debt_ratio"] is False

    def test_passes_none_debt_ratio(self) -> None:
        """부채비율 데이터 없으면 조건 완화 (보수적이지 않게)."""
        f = {**self._valid, "debt_ratio": None}
        passed, details = passes_fundamental_filter("TEST", "KR", f)
        assert details["ok_debt_ratio"] is True

    def test_fails_none_market_cap(self) -> None:
        f = {**self._valid, "market_cap": None}
        passed, _ = passes_fundamental_filter("TEST", "KR", f)
        assert passed is False

    def test_details_contains_kr_keys(self) -> None:
        _, details = passes_fundamental_filter("TEST", "KR", self._valid)
        for key in ("ok_market_cap", "ok_per", "ok_debt_ratio", "passed"):
            assert key in details

    def test_exact_market_cap_boundary(self) -> None:
        """시가총액이 정확히 임계값이면 통과."""
        f = {**self._valid, "market_cap": float(MIN_MARKET_CAP_KRW)}
        passed, details = passes_fundamental_filter("TEST", "KR", f)
        assert details["ok_market_cap"] is True

    def test_case_insensitive_market(self) -> None:
        passed, _ = passes_fundamental_filter("TEST", "kr", self._valid)
        assert passed is True


# ---------------------------------------------------------------------------
# US 필터 테스트
# ---------------------------------------------------------------------------

class TestFundamentalFilterUS:
    _valid = {
        "market_cap": MIN_MARKET_CAP_USD + 1e8,
        "per": 20.0,
        "debt_ratio": 150.0,  # US는 부채비율 조건 없음
    }

    def test_passes_all_valid(self) -> None:
        passed, _ = passes_fundamental_filter("AAPL", "US", self._valid)
        assert passed is True

    def test_fails_low_market_cap(self) -> None:
        f = {**self._valid, "market_cap": MIN_MARKET_CAP_USD * 0.5}
        passed, details = passes_fundamental_filter("TEST", "US", f)
        assert passed is False
        assert details["ok_market_cap"] is False

    def test_fails_negative_per(self) -> None:
        f = {**self._valid, "per": -10.0}
        passed, details = passes_fundamental_filter("TEST", "US", f)
        assert passed is False
        assert details["ok_per"] is False

    def test_high_debt_ratio_passes_us(self) -> None:
        """US는 부채비율 조건이 없으므로 200% 초과도 통과."""
        f = {**self._valid, "debt_ratio": 500.0}
        passed, _ = passes_fundamental_filter("TEST", "US", f)
        assert passed is True

    def test_details_has_no_debt_ratio_key(self) -> None:
        """US details에는 ok_debt_ratio 키가 없다."""
        _, details = passes_fundamental_filter("TEST", "US", self._valid)
        assert "ok_debt_ratio" not in details

    def test_details_contains_us_keys(self) -> None:
        _, details = passes_fundamental_filter("TEST", "US", self._valid)
        for key in ("ok_market_cap", "ok_per", "passed"):
            assert key in details
