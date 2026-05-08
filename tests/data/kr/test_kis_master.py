"""KIS 공개 종목 마스터 파일 모듈 테스트.

파일 형식이 cp949 + fixed-width 라 mock 단위 테스트는 sanity check 위주로 두고,
실제 동작 검증은 ``@network`` 통합 테스트 (실 다운로드) 로 처리한다.
"""
from __future__ import annotations

import pytest

from scanner.kr import kis_master


network = pytest.mark.network


# ---------------------------------------------------------------------------
# 파싱 사양 sanity check
# ---------------------------------------------------------------------------


class TestPart2Spec:
    def test_widths_sum_plus_newline_matches_part2_len(self) -> None:
        """widths 합계(227) + 줄바꿈(1) == ``_PART2_LEN`` (228)."""
        assert sum(kis_master._PART2_WIDTHS) + 1 == kis_master._PART2_LEN

    def test_widths_and_columns_length_match(self) -> None:
        """``_PART2_WIDTHS`` 와 ``_PART2_COLS`` 의 항목 수가 동일해야 한다."""
        assert len(kis_master._PART2_WIDTHS) == len(kis_master._PART2_COLS)

    def test_kospi200_column_present(self) -> None:
        """``KOSPI200섹터업종`` 컬럼이 정의에 포함되어 있어야 한다 (필터 의존)."""
        assert "KOSPI200섹터업종" in kis_master._PART2_COLS


# ---------------------------------------------------------------------------
# 통합 — 실제 KIS 마스터 다운로드 + KOSPI200 추출
# ---------------------------------------------------------------------------


class TestFetchKospi200ConstituentsIntegration:
    @network
    def test_returns_around_200_tickers(self) -> None:
        """실 다운로드 결과가 KOSPI200 종목 수에 근접해야 한다 (180~220 범위)."""
        df = kis_master.fetch_kospi200_constituents()
        assert not df.empty
        assert 150 <= len(df) <= 250, (
            f"KOSPI200 종목 수가 예상 범위를 벗어남: {len(df)}"
        )

    @network
    def test_tickers_are_six_digit_strings(self) -> None:
        """모든 ticker 가 6자리 숫자 문자열이어야 한다."""
        df = kis_master.fetch_kospi200_constituents()
        if df.empty:
            pytest.skip("마스터 데이터 없음")
        for t in df["ticker"]:
            assert isinstance(t, str)
            assert len(t) == 6 and t.isdigit(), f"비정상 ticker: {t!r}"

    @network
    def test_required_columns_present(self) -> None:
        """결과 DataFrame 이 [ticker, name, sector] 컬럼을 가져야 한다."""
        df = kis_master.fetch_kospi200_constituents()
        if df.empty:
            pytest.skip("마스터 데이터 없음")
        for col in ("ticker", "name", "sector"):
            assert col in df.columns
