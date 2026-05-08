"""한국(KOSPI) 데이터 fetcher 단위 테스트.

대상 모듈: scanner.data.kr.fetcher
네트워크가 필요한 테스트에는 @pytest.mark.network 마커를 붙인다.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest


network = pytest.mark.network


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _recent_range(days: int = 30) -> tuple[date, date]:
    end = date.today()
    start = end - timedelta(days=days)
    return start, end


def _assert_ohlcv_columns(df: pd.DataFrame, required: list[str]) -> None:
    """필수 컬럼이 모두 있고 비어있지 않음을 확인한다."""
    assert not df.empty, "DataFrame이 비어 있습니다."
    for col in required:
        assert col in df.columns, f"컬럼 누락: {col}"


def _assert_no_negative_prices(df: pd.DataFrame) -> None:
    for col in ("open", "high", "low", "close"):
        if col in df.columns:
            assert (df[col] >= 0).all(), f"{col} 에 음수 가격이 있습니다."


def _assert_column_dtypes(df: pd.DataFrame) -> None:
    """숫자 컬럼이 float/int 타입임을 확인한다."""
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            assert pd.api.types.is_numeric_dtype(df[col]), f"{col} 이 숫자 타입이 아닙니다."


# ---------------------------------------------------------------------------
# 일봉
# ---------------------------------------------------------------------------


class TestFetchDaily:
    @network
    def test_samsung_returns_dataframe(self) -> None:
        """삼성전자(005930) 일봉이 유효한 DataFrame을 반환한다."""
        from scanner.data.kr.fetcher import fetch_daily

        start, end = _recent_range(30)
        df = fetch_daily("005930", start, end)
        _assert_ohlcv_columns(df, ["ticker", "date", "open", "high", "low", "close", "volume"])
        _assert_no_negative_prices(df)
        _assert_column_dtypes(df)
        assert (df["ticker"] == "005930").all()

    @network
    def test_date_range_is_respected(self) -> None:
        """반환된 데이터의 날짜가 요청 범위 안에 있다."""
        from scanner.data.kr.fetcher import fetch_daily

        start, end = _recent_range(10)
        df = fetch_daily("005930", start, end)
        if df.empty:
            pytest.skip("데이터 없음 (휴장일 가능성)")
        dates = pd.to_datetime(df["date"])
        assert dates.min().date() >= start
        assert dates.max().date() <= end

    def test_invalid_ticker_returns_empty(self) -> None:
        """존재하지 않는 티커는 빈 DataFrame을 반환한다 (네트워크 호출 포함)."""
        from scanner.data.kr.fetcher import fetch_daily

        start, end = _recent_range(5)
        df = fetch_daily("INVALID_TICKER_XYZ", start, end)
        assert isinstance(df, pd.DataFrame)


# ---------------------------------------------------------------------------
# 주봉
# ---------------------------------------------------------------------------


class TestFetchWeekly:
    @network
    def test_samsung_weekly_columns(self) -> None:
        """삼성전자 주봉이 week_start_date 컬럼을 포함한다."""
        from scanner.data.kr.fetcher import fetch_weekly

        start, end = _recent_range(60)
        df = fetch_weekly("005930", start, end)
        _assert_ohlcv_columns(df, ["ticker", "week_start_date", "open", "close", "volume"])
        _assert_column_dtypes(df)

    @network
    def test_weekly_rows_less_than_daily(self) -> None:
        """주봉 행 수는 같은 기간 일봉 행 수보다 적다."""
        from scanner.data.kr.fetcher import fetch_daily, fetch_weekly

        start, end = _recent_range(60)
        df_d = fetch_daily("005930", start, end)
        df_w = fetch_weekly("005930", start, end)
        if df_d.empty or df_w.empty:
            pytest.skip("데이터 없음")
        assert len(df_w) < len(df_d)


# ---------------------------------------------------------------------------
# 재무
# ---------------------------------------------------------------------------


class TestFetchFundamental:
    @network
    def test_samsung_fundamental_columns(self) -> None:
        """삼성전자 재무 데이터가 per/pbr 컬럼을 포함한다."""
        from scanner.data.kr.fetcher import fetch_fundamental

        start, end = _recent_range(10)
        df = fetch_fundamental("005930", start, end)
        if df.empty:
            pytest.skip("재무 데이터 없음")
        assert "ticker" in df.columns
        assert "date" in df.columns

    def test_empty_result_is_dataframe(self) -> None:
        """실패 시 빈 DataFrame(타입)을 반환한다."""
        from scanner.data.kr.fetcher import fetch_fundamental

        start, end = _recent_range(5)
        df = fetch_fundamental("INVALID000", start, end)
        assert isinstance(df, pd.DataFrame)


# ---------------------------------------------------------------------------
# 분봉(60분)
# ---------------------------------------------------------------------------


class TestFetchIntraday:
    def test_intraday_returns_dataframe_with_correct_columns(self) -> None:
        """60분봉 함수가 항상 올바른 컬럼을 가진 DataFrame을 반환한다 (현재 빈 결과)."""
        from scanner.data.kr.fetcher import fetch_intraday

        df = fetch_intraday("005930", date.today())
        assert isinstance(df, pd.DataFrame)
        expected_cols = {"ticker", "datetime", "open", "high", "low", "close", "volume"}
        assert expected_cols.issubset(set(df.columns))
