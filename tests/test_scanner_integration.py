"""스캐너 통합 테스트.

analyze_ticker() / scan_universe() / save_scan_results() / get_scan_results() 의
end-to-end 흐름을 in-memory SQLite로 검증한다.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from scanner.config import MIN_AVG_TRADING_VALUE_KRW
from scanner.db.models import Base
from scanner.db.repository import get_scan_results, save_scan_results
from scanner.us.scanner import TickerScanResult, analyze_ticker, scan_universe

FIXTURE_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# in-memory DB 픽스처
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def mem_session():
    """테스트 전용 in-memory SQLite 세션."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Factory()
    yield session
    session.close()
    engine.dispose()


# ---------------------------------------------------------------------------
# DataFrame 픽스처
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def pullback_df() -> pd.DataFrame:
    df = pd.read_csv(str(FIXTURE_DIR / "pullback_detected.csv"), parse_dates=["date"])
    df["date"] = df["date"].dt.date
    return df


@pytest.fixture(scope="module")
def box_df() -> pd.DataFrame:
    df = pd.read_csv(str(FIXTURE_DIR / "box_breakout_detected.csv"), parse_dates=["date"])
    df["date"] = df["date"].dt.date
    return df


@pytest.fixture(scope="module")
def no_signal_df() -> pd.DataFrame:
    """어떤 패턴도 탐지되지 않는 하락 추세 데이터."""
    df = pd.read_csv(str(FIXTURE_DIR / "pullback_no_signal.csv"), parse_dates=["date"])
    df["date"] = df["date"].dt.date
    return df


def _valid_fundamentals_kr() -> dict:
    return {
        "market_cap": MIN_AVG_TRADING_VALUE_KRW * 20,  # 1조원
        "per": 12.0,
        "debt_ratio": 80.0,
    }


# ---------------------------------------------------------------------------
# analyze_ticker 테스트
# ---------------------------------------------------------------------------

class TestAnalyzeTicker:
    def test_returns_ticker_scan_result(self, pullback_df: pd.DataFrame) -> None:
        res = analyze_ticker("TEST_PB", "KR", pullback_df)
        assert isinstance(res, TickerScanResult)

    def test_pullback_pattern_detected(self, pullback_df: pd.DataFrame) -> None:
        res = analyze_ticker("TEST_PB", "KR", pullback_df)
        assert any(p.pattern_name == "pullback" for p in res.pattern_results)

    def test_confidence_scores_count_matches_patterns(self, pullback_df: pd.DataFrame) -> None:
        res = analyze_ticker("TEST_PB", "KR", pullback_df)
        assert len(res.confidence_scores) == len(res.pattern_results)

    def test_confidence_score_in_range(self, pullback_df: pd.DataFrame) -> None:
        res = analyze_ticker("TEST_PB", "KR", pullback_df)
        for score in res.confidence_scores:
            assert 0.0 <= score <= 100.0

    def test_no_pattern_on_downtrend(self, no_signal_df: pd.DataFrame) -> None:
        res = analyze_ticker("TEST_DOWN", "KR", no_signal_df)
        assert len(res.pattern_results) == 0

    def test_volume_filter_runs(self, pullback_df: pd.DataFrame) -> None:
        res = analyze_ticker("TEST_PB", "KR", pullback_df)
        assert "ok_value" in res.volume_details

    def test_fundamental_filter_runs_when_provided(self, pullback_df: pd.DataFrame) -> None:
        res = analyze_ticker("TEST_PB", "KR", pullback_df, _valid_fundamentals_kr())
        assert "ok_market_cap" in res.fundamental_details

    def test_fundamental_filter_skipped_when_none(self, pullback_df: pd.DataFrame) -> None:
        res = analyze_ticker("TEST_PB", "KR", pullback_df, None)
        assert res.passed_fundamental is False
        assert res.fundamental_details == {}

    def test_empty_df_returns_empty_result(self) -> None:
        res = analyze_ticker("EMPTY", "KR", pd.DataFrame())
        assert len(res.pattern_results) == 0


# ---------------------------------------------------------------------------
# scan_universe 테스트
# ---------------------------------------------------------------------------

class TestScanUniverse:
    def test_returns_list(self, pullback_df: pd.DataFrame, no_signal_df: pd.DataFrame) -> None:
        daily_dfs = {"PB": pullback_df, "DOWN": no_signal_df}
        market_map = {"PB": "KR", "DOWN": "KR"}
        results = scan_universe(daily_dfs, market_map, max_workers=2)
        assert isinstance(results, list)
        assert len(results) == 2

    def test_all_tickers_processed(self, pullback_df: pd.DataFrame, no_signal_df: pd.DataFrame) -> None:
        daily_dfs = {"PB": pullback_df, "DOWN": no_signal_df}
        market_map = {"PB": "KR", "DOWN": "KR"}
        results = scan_universe(daily_dfs, market_map, max_workers=2)
        tickers = {r.ticker for r in results}
        assert "PB" in tickers
        assert "DOWN" in tickers

    def test_with_fundamentals_map(self, pullback_df: pd.DataFrame) -> None:
        daily_dfs = {"PB": pullback_df}
        market_map = {"PB": "KR"}
        fund_map = {"PB": _valid_fundamentals_kr()}
        results = scan_universe(daily_dfs, market_map, fundamentals_map=fund_map, max_workers=1)
        assert len(results) == 1
        assert results[0].fundamental_details != {}


# ---------------------------------------------------------------------------
# save / get scan_results 테스트
# ---------------------------------------------------------------------------

class TestRepository:
    def test_save_returns_count(self, pullback_df: pd.DataFrame, mem_session: Session) -> None:
        res = analyze_ticker("SAVE_TEST", "KR", pullback_df)
        count = save_scan_results([res], mem_session)
        mem_session.commit()
        assert count == len(res.pattern_results)

    def test_get_returns_saved_rows(self, pullback_df: pd.DataFrame, mem_session: Session) -> None:
        today = date.today()
        res = analyze_ticker("GET_TEST", "KR", pullback_df)
        res.scan_date = today
        save_scan_results([res], mem_session)
        mem_session.commit()

        rows = get_scan_results(today, mem_session, market_tickers=["GET_TEST"])
        assert len(rows) >= 1
        assert rows[0].ticker == "GET_TEST"

    def test_get_with_min_score(self, pullback_df: pd.DataFrame, mem_session: Session) -> None:
        today = date.today()
        res = analyze_ticker("SCORE_TEST", "KR", pullback_df)
        res.scan_date = today
        save_scan_results([res], mem_session)
        mem_session.commit()

        all_rows = get_scan_results(today, mem_session, market_tickers=["SCORE_TEST"])
        high_rows = get_scan_results(today, mem_session, market_tickers=["SCORE_TEST"], min_score=99.9)
        assert len(high_rows) <= len(all_rows)

    def test_save_empty_results_returns_zero(self, mem_session: Session) -> None:
        count = save_scan_results([], mem_session)
        assert count == 0

    def test_re_save_replaces_previous(self, pullback_df: pd.DataFrame, mem_session: Session) -> None:
        """같은 날짜/종목 재저장 시 중복 없이 교체된다."""
        fixed_date = date(2026, 1, 1)
        res = analyze_ticker("REPLACE_TEST", "KR", pullback_df)
        res.scan_date = fixed_date

        save_scan_results([res], mem_session)
        mem_session.commit()
        count_before = len(get_scan_results(fixed_date, mem_session, market_tickers=["REPLACE_TEST"]))

        save_scan_results([res], mem_session)
        mem_session.commit()
        count_after = len(get_scan_results(fixed_date, mem_session, market_tickers=["REPLACE_TEST"]))

        assert count_after == count_before
