"""CLI 통합 테스트.

typer.testing.CliRunner 를 사용해 실제 DB·네트워크 호출 없이
CLI 명령어의 인자 파싱·exit-code·출력을 검증한다.

모든 임포트가 함수 내부에서 이뤄지므로, patch 대상은 소스 모듈 경로를 사용한다.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from scanner.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# 공통 헬퍼
# ---------------------------------------------------------------------------

def _mock_scan_row(
    ticker: str = "TEST",
    pattern_name: str = "pullback",
    score: float = 75.0,
) -> MagicMock:
    """ScanResult ORM 행 목(mock)을 생성한다."""
    row = MagicMock()
    row.ticker = ticker
    row.pattern_name = pattern_name
    row.confidence_score = score
    row.entry_price = 100.0
    row.stop_loss = 95.0
    row.target_price = 110.0
    row.risk_reward_ratio = 2.0
    row.trend_weekly = "uptrend"
    row.passed_filters = True
    row.pattern_details = {}
    return row


@contextmanager
def _noop_session():
    """아무 동작도 하지 않는 더미 세션 컨텍스트 매니저."""
    yield MagicMock()


# ---------------------------------------------------------------------------
# --help 테스트 (임포트 없이 빠르게 실행)
# ---------------------------------------------------------------------------

class TestHelp:
    def test_root_help(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "스윙매매" in result.output

    def test_scan_help(self) -> None:
        result = runner.invoke(app, ["scan", "--help"])
        assert result.exit_code == 0
        assert "--market" in result.output
        assert "--min-confidence" in result.output
        assert "--skip-fetch" in result.output

    def test_results_help(self) -> None:
        result = runner.invoke(app, ["results", "--help"])
        assert result.exit_code == 0
        assert "--date" in result.output
        assert "--pattern" in result.output

    def test_show_help(self) -> None:
        result = runner.invoke(app, ["show", "--help"])
        assert result.exit_code == 0

    def test_version_help(self) -> None:
        result = runner.invoke(app, ["version", "--help"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# version 명령어
# ---------------------------------------------------------------------------

class TestVersion:
    def test_version_outputs_string(self) -> None:
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "swing-scanner" in result.output


# ---------------------------------------------------------------------------
# scan 명령어 (mock 기반)
# ---------------------------------------------------------------------------

_SCAN_PATCHES = [
    "scanner.config.setup_logger",
    "scanner.db.migrations.init_database",
    "scanner.pipeline._maybe_update_universe",
    "scanner.data.universe.get_active_tickers",
    "scanner.pipeline._load_daily_dfs",
    "scanner.pipeline._load_market_map",
    "scanner.pipeline._load_fundamentals",
    "scanner.scanner.analyze_ticker",
    "scanner.db.session.get_session",
    "scanner.db.repository.save_scan_results",
    "scanner.db.repository.get_scan_results",
]


def _apply_scan_patches(
    *,
    tickers: list = None,
    daily_dfs: dict = None,
    analyze_ret: MagicMock = None,
    save_ret: int = 0,
    get_ret: list = None,
):
    """scan 명령어 실행에 필요한 patch 스택을 반환한다."""
    tickers = tickers if tickers is not None else []
    daily_dfs = daily_dfs if daily_dfs is not None else {}
    get_ret = get_ret if get_ret is not None else []

    def _build_analyze_ret():
        m = MagicMock()
        m.pattern_results = []
        m.confidence_scores = []
        m.passed_volume = True
        m.volume_details = {}
        m.passed_fundamental = False
        m.fundamental_details = {}
        m.scan_date = date.today()
        return m

    if analyze_ret is None:
        analyze_ret = _build_analyze_ret()

    patches = [
        patch("scanner.config.setup_logger"),
        patch("scanner.db.migrations.init_database"),
        patch("scanner.pipeline._maybe_update_universe"),
        patch("scanner.data.universe.get_active_tickers", return_value=tickers),
        patch("scanner.pipeline._load_daily_dfs", return_value=daily_dfs),
        patch("scanner.pipeline._load_market_map", return_value={t: "KR" for t in daily_dfs}),
        patch("scanner.pipeline._load_fundamentals", return_value={}),
        patch("scanner.scanner.analyze_ticker", return_value=analyze_ret),
        patch("scanner.db.session.get_session", side_effect=_noop_session),
        patch("scanner.db.repository.save_scan_results", return_value=save_ret),
        patch("scanner.db.repository.get_scan_results", return_value=get_ret),
    ]
    return patches


class TestScan:
    def test_scan_empty_universe_exits_zero(self) -> None:
        """활성 종목이 없을 때 exit 0 + 경고 메시지."""
        for p in _apply_scan_patches(tickers=[], daily_dfs={}):
            p.start()
        try:
            result = runner.invoke(app, ["scan", "--skip-fetch"])
        finally:
            patch.stopall()

        assert result.exit_code == 0
        assert "활성 종목" in result.output

    def test_scan_exits_zero_with_one_ticker(self) -> None:
        """종목 1개 처리 후 exit 0."""
        ticker_df = MagicMock()
        for p in _apply_scan_patches(tickers=["A"], daily_dfs={"A": ticker_df}):
            p.start()
        try:
            result = runner.invoke(app, ["scan", "--skip-fetch", "--market", "kr"])
        finally:
            patch.stopall()

        assert result.exit_code == 0

    def test_scan_summary_panel_shown(self) -> None:
        """스캔 완료 후 요약 패널이 출력된다."""
        ticker_df = MagicMock()
        for p in _apply_scan_patches(tickers=["A"], daily_dfs={"A": ticker_df}):
            p.start()
        try:
            result = runner.invoke(app, ["scan", "--skip-fetch"])
        finally:
            patch.stopall()

        assert result.exit_code == 0
        assert "스캔 완료" in result.output

    def test_scan_top10_shown_when_results_exist(self) -> None:
        """get_scan_results 가 결과를 반환하면 TOP 10 테이블이 출력된다."""
        ticker_df = MagicMock()
        mock_rows = [_mock_scan_row()]
        for p in _apply_scan_patches(
            tickers=["A"], daily_dfs={"A": ticker_df}, get_ret=mock_rows
        ):
            p.start()
        try:
            result = runner.invoke(app, ["scan", "--skip-fetch"])
        finally:
            patch.stopall()

        assert result.exit_code == 0
        assert "TOP 10" in result.output

    def test_scan_invalid_market_still_runs(self) -> None:
        """알 수 없는 시장 코드도 파싱 에러 없이 통과한다 (유니버스 0개로 종료)."""
        for p in _apply_scan_patches():
            p.start()
        try:
            result = runner.invoke(app, ["scan", "--skip-fetch", "--market", "jp"])
        finally:
            patch.stopall()

        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# results 명령어
# ---------------------------------------------------------------------------

_RESULTS_PATCHES_BASE = [
    "scanner.config.setup_logger",
    "scanner.db.migrations.init_database",
    "scanner.db.session.get_session",
    "scanner.db.repository.get_scan_results",
]


class TestResults:
    def test_results_no_data_exits_zero(self) -> None:
        """결과가 없을 때 exit 0 + 안내 메시지."""
        with (
            patch("scanner.config.setup_logger"),
            patch("scanner.db.migrations.init_database"),
            patch("scanner.db.session.get_session", side_effect=_noop_session),
            patch("scanner.db.repository.get_scan_results", return_value=[]),
        ):
            result = runner.invoke(app, ["results", "--date", "2026-01-01"])

        assert result.exit_code == 0
        assert "없습니다" in result.output

    def test_results_with_data_shows_table(self) -> None:
        """결과가 있으면 테이블이 출력된다."""
        with (
            patch("scanner.config.setup_logger"),
            patch("scanner.db.migrations.init_database"),
            patch("scanner.db.session.get_session", side_effect=_noop_session),
            patch("scanner.db.repository.get_scan_results", return_value=[_mock_scan_row()]),
        ):
            result = runner.invoke(app, ["results", "--date", "2026-01-01"])

        assert result.exit_code == 0
        assert "TEST" in result.output

    def test_results_invalid_date_exits_nonzero(self) -> None:
        """잘못된 날짜 형식 → exit 1."""
        with (
            patch("scanner.config.setup_logger"),
            patch("scanner.db.migrations.init_database"),
        ):
            result = runner.invoke(app, ["results", "--date", "not-a-date"])

        assert result.exit_code != 0

    def test_results_pattern_filter_no_match_shows_empty(self) -> None:
        """--pattern 이 일치하지 않으면 '없습니다' 메시지."""
        with (
            patch("scanner.config.setup_logger"),
            patch("scanner.db.migrations.init_database"),
            patch("scanner.db.session.get_session", side_effect=_noop_session),
            patch("scanner.db.repository.get_scan_results", return_value=[_mock_scan_row(pattern_name="pullback")]),
        ):
            result = runner.invoke(app, ["results", "--pattern", "golden_cross"])

        assert result.exit_code == 0
        assert "없습니다" in result.output

    def test_results_pattern_filter_match(self) -> None:
        """--pattern 이 일치하면 결과를 출력한다."""
        with (
            patch("scanner.config.setup_logger"),
            patch("scanner.db.migrations.init_database"),
            patch("scanner.db.session.get_session", side_effect=_noop_session),
            patch("scanner.db.repository.get_scan_results", return_value=[_mock_scan_row(pattern_name="pullback")]),
        ):
            result = runner.invoke(app, ["results", "--pattern", "pullback"])

        assert result.exit_code == 0
        assert "TEST" in result.output


# ---------------------------------------------------------------------------
# show 명령어
# ---------------------------------------------------------------------------

def _session_returning(rows: list):
    """주어진 rows를 scalars().all() 로 반환하는 세션 컨텍스트 매니저를 만든다."""
    @contextmanager
    def _ctx():
        session = MagicMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = rows
        session.execute.return_value = result_mock
        yield session
    return _ctx


class TestShow:
    def test_show_no_result_exits_zero(self) -> None:
        """결과 없으면 exit 0 + 안내 메시지."""
        with (
            patch("scanner.config.setup_logger"),
            patch("scanner.db.migrations.init_database"),
            patch("scanner.db.session.get_session", side_effect=_session_returning([])),
        ):
            result = runner.invoke(app, ["show", "AAPL", "--date", "2026-01-01"])

        assert result.exit_code == 0
        assert "없습니다" in result.output

    def test_show_with_result_renders_panel(self) -> None:
        """결과가 있으면 패널이 출력된다."""
        row = _mock_scan_row(ticker="AAPL", pattern_name="pullback")
        row.pattern_details = {"weekly_trend": "uptrend"}

        with (
            patch("scanner.config.setup_logger"),
            patch("scanner.db.migrations.init_database"),
            patch("scanner.db.session.get_session", side_effect=_session_returning([row])),
        ):
            result = runner.invoke(app, ["show", "AAPL"])

        assert result.exit_code == 0
        assert "AAPL" in result.output
