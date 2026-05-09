"""KIS OpenAPI 클라이언트 mock 단위 테스트.

httpx 호출을 monkeypatch 로 가짜 응답으로 대체해
get_access_token / fetch_daily_chart / fetch_financial_ratio /
_request 의 동작과 토큰 캐싱 / 페이징 / 재시도 로직을 검증한다.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from scanner.kr import kis_api


# ---------------------------------------------------------------------------
# 픽스처
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _kis_test_env(monkeypatch, tmp_path):
    """모든 테스트에 임시 자격증명·캐시 경로·짧은 재시도 설정을 주입한다."""
    monkeypatch.setattr(kis_api, "KIS_APP_KEY", "test-app-key")
    monkeypatch.setattr(kis_api, "KIS_APP_SECRET", "test-app-secret")
    monkeypatch.setattr(kis_api, "KIS_BASE_URL", "https://test.kis.local")
    monkeypatch.setattr(
        kis_api, "KIS_TOKEN_CACHE_PATH", tmp_path / ".kis_token.json"
    )
    monkeypatch.setattr(kis_api, "KIS_RATE_LIMIT_SECONDS", 0)
    monkeypatch.setattr(kis_api, "FETCH_RETRY_MAX", 2)
    monkeypatch.setattr(kis_api, "FETCH_RETRY_BACKOFF_BASE", 1.0)


def _make_response(json_data: dict, status_code: int = 200) -> MagicMock:
    """httpx.Response 더블."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


def _seed_token_cache(expires_in_seconds: int = 23 * 3600) -> None:
    """토큰 캐시 파일을 미리 생성한다."""
    expires_at = datetime.now() + timedelta(seconds=expires_in_seconds)
    kis_api.KIS_TOKEN_CACHE_PATH.write_text(
        json.dumps(
            {"access_token": "seeded-tok", "expires_at": expires_at.isoformat()}
        ),
        encoding="utf-8",
    )


def _sample_daily_response(
    rows: list[tuple[str, float, float, float, float, float]],
) -> dict:
    """KIS 일봉 응답 더블. rows: [(YYYYMMDD, open, high, low, close, volume), ...]"""
    return {
        "rt_cd": "0",
        "msg_cd": "MCA00000",
        "msg1": "정상처리되었습니다.",
        "output1": {},
        "output2": [
            {
                "stck_bsop_date": d,
                "stck_oprc": str(o),
                "stck_hgpr": str(h),
                "stck_lwpr": str(low),
                "stck_clpr": str(c),
                "acml_vol": str(v),
                "acml_tr_pbmn": str(int(v * c)),
            }
            for d, o, h, low, c, v in rows
        ],
    }


# ---------------------------------------------------------------------------
# get_access_token
# ---------------------------------------------------------------------------


class TestGetAccessToken:
    def test_issues_new_token_when_no_cache(self, monkeypatch):
        """캐시 파일이 없으면 신규 발급한다."""
        mock_post = MagicMock(
            return_value=_make_response(
                {"access_token": "tok-1", "expires_in": 86400}
            )
        )
        monkeypatch.setattr(kis_api.httpx, "post", mock_post)

        token = kis_api.get_access_token()

        assert token == "tok-1"
        assert mock_post.call_count == 1
        assert kis_api.KIS_TOKEN_CACHE_PATH.exists()

    def test_reuses_cached_token_when_valid(self, monkeypatch):
        """캐시가 유효(만료 여유 충분)하면 발급 호출을 건너뛴다."""
        _seed_token_cache(expires_in_seconds=3600)  # 1시간 후 만료
        mock_post = MagicMock()
        monkeypatch.setattr(kis_api.httpx, "post", mock_post)

        token = kis_api.get_access_token()

        assert token == "seeded-tok"
        assert mock_post.call_count == 0

    def test_refreshes_when_near_expiry(self, monkeypatch):
        """만료 10분 미만이면 재발급한다."""
        _seed_token_cache(expires_in_seconds=60)  # 1분 후 만료
        mock_post = MagicMock(
            return_value=_make_response(
                {"access_token": "fresh-tok", "expires_in": 86400}
            )
        )
        monkeypatch.setattr(kis_api.httpx, "post", mock_post)

        token = kis_api.get_access_token()

        assert token == "fresh-tok"
        assert mock_post.call_count == 1

    def test_force_refresh_bypasses_cache(self, monkeypatch):
        """force_refresh=True 면 유효 캐시도 무시하고 재발급."""
        _seed_token_cache(expires_in_seconds=3600)
        mock_post = MagicMock(
            return_value=_make_response(
                {"access_token": "forced-tok", "expires_in": 86400}
            )
        )
        monkeypatch.setattr(kis_api.httpx, "post", mock_post)

        token = kis_api.get_access_token(force_refresh=True)

        assert token == "forced-tok"
        assert mock_post.call_count == 1

    def test_raises_when_credentials_missing(self, monkeypatch):
        """KIS_APP_KEY 가 빈 값이면 RuntimeError."""
        monkeypatch.setattr(kis_api, "KIS_APP_KEY", "")
        with pytest.raises(RuntimeError, match="KIS_APP_KEY"):
            kis_api.get_access_token()


# ---------------------------------------------------------------------------
# fetch_daily_chart
# ---------------------------------------------------------------------------


class TestFetchDailyChart:
    def test_single_chunk_returns_normalized_dataframe(self, monkeypatch):
        """단일 청크 응답을 [ticker, date, open, ...] 컬럼으로 정규화한다."""
        _seed_token_cache()
        mock_request = MagicMock(
            return_value=_make_response(
                _sample_daily_response(
                    [
                        ("20260101", 100, 110, 95, 105, 1000),
                        ("20260102", 105, 115, 100, 112, 2000),
                    ]
                )
            )
        )
        monkeypatch.setattr(kis_api.httpx, "request", mock_request)

        df = kis_api.fetch_daily_chart(
            "005930", date(2026, 1, 1), date(2026, 1, 5)
        )

        assert list(df.columns) == [
            "ticker", "date", "open", "high", "low", "close", "volume", "value",
        ]
        assert len(df) == 2
        assert df.iloc[0]["ticker"] == "005930"
        assert df.iloc[0]["close"] == 105.0
        assert df.iloc[1]["close"] == 112.0

    def test_paginates_when_range_exceeds_chunk(self, monkeypatch):
        """KIS_DAILY_CHUNK_DAYS 보다 긴 기간은 자동 분할 호출한다."""
        _seed_token_cache()
        monkeypatch.setattr(kis_api, "KIS_DAILY_CHUNK_DAYS", 100)

        call_ranges: list[tuple[str, str]] = []

        def fake_request(method, url, **kwargs):
            params = kwargs["params"]
            call_ranges.append(
                (params["FID_INPUT_DATE_1"], params["FID_INPUT_DATE_2"])
            )
            return _make_response(
                _sample_daily_response(
                    [(params["FID_INPUT_DATE_1"], 100, 100, 100, 100, 1000)]
                )
            )

        monkeypatch.setattr(kis_api.httpx, "request", fake_request)

        df = kis_api.fetch_daily_chart(
            "005930", date(2026, 1, 1), date(2026, 12, 31)
        )

        # 365일 / 100일 = 4 청크
        assert len(call_ranges) == 4
        assert len(df) == 4
        # 청크 시작일이 시간순으로 정렬됨
        assert call_ranges[0][0] == "20260101"
        assert call_ranges[-1][1] == "20261231"

    def test_returns_empty_dataframe_when_no_data(self, monkeypatch):
        """output2 가 빈 배열이면 빈 DataFrame 반환."""
        _seed_token_cache()
        mock_request = MagicMock(
            return_value=_make_response(
                {"rt_cd": "0", "msg1": "정상", "output1": {}, "output2": []}
            )
        )
        monkeypatch.setattr(kis_api.httpx, "request", mock_request)

        df = kis_api.fetch_daily_chart(
            "999999", date(2026, 1, 1), date(2026, 1, 5)
        )

        assert df.empty

    def test_returns_empty_when_start_after_end(self, monkeypatch):
        """start > end 이면 호출 없이 빈 DataFrame 반환."""
        _seed_token_cache()
        mock_request = MagicMock()
        monkeypatch.setattr(kis_api.httpx, "request", mock_request)

        df = kis_api.fetch_daily_chart(
            "005930", date(2026, 12, 31), date(2026, 1, 1)
        )

        assert df.empty
        assert mock_request.call_count == 0


# ---------------------------------------------------------------------------
# fetch_financial_ratio
# ---------------------------------------------------------------------------


class TestFetchFinancialRatio:
    def test_returns_latest_row_normalized(self, monkeypatch):
        """output 첫 행에서 lblt_rate→debt_ratio, roe_val→roe 만 추출한다."""
        _seed_token_cache()
        mock_request = MagicMock(
            return_value=_make_response(
                {
                    "rt_cd": "0",
                    "msg1": "정상",
                    "output": [
                        # 가장 최근 결산 (실제 KIS 응답 형태)
                        {
                            "stac_yymm": "202512",
                            "grs": "10.88",
                            "bsop_prfi_inrt": "33.23",
                            "ntin_inrt": "31.22",
                            "roe_val": "10.85",
                            "eps": "6564.00",
                            "sps": "49471",
                            "bps": "63997.00",
                            "rsrv_rate": "45296.17",
                            "lblt_rate": "29.94",
                        },
                        # 더 오래된 결산 (무시됨)
                        {
                            "stac_yymm": "202412",
                            "roe_val": "9.0",
                            "lblt_rate": "31.0",
                        },
                    ],
                }
            )
        )
        monkeypatch.setattr(kis_api.httpx, "request", mock_request)

        df = kis_api.fetch_financial_ratio("005930")

        assert len(df) == 1
        row = df.iloc[0]
        assert row["ticker"] == "005930"
        assert row["debt_ratio"] == 29.94
        assert row["roe"] == 10.85
        # 미수집 필드는 컬럼에 없음
        for col in ("per", "pbr", "stac_yymm", "eps", "bps"):
            assert col not in df.columns

    def test_returns_empty_when_no_output(self, monkeypatch):
        """output 가 빈 배열이면 빈 DataFrame."""
        _seed_token_cache()
        mock_request = MagicMock(
            return_value=_make_response(
                {"rt_cd": "0", "msg1": "정상", "output": []}
            )
        )
        monkeypatch.setattr(kis_api.httpx, "request", mock_request)

        df = kis_api.fetch_financial_ratio("999999")

        assert df.empty


# ---------------------------------------------------------------------------
# _request (재시도 + rt_cd 검증)
# ---------------------------------------------------------------------------


class TestRequest:
    def test_retries_then_raises_on_business_error(self, monkeypatch):
        """rt_cd != "0" 면 FETCH_RETRY_MAX 회 재시도 후 RuntimeError."""
        _seed_token_cache()
        mock_request = MagicMock(
            return_value=_make_response(
                {"rt_cd": "1", "msg_cd": "FOO", "msg1": "오류"}
            )
        )
        monkeypatch.setattr(kis_api.httpx, "request", mock_request)

        with pytest.raises(RuntimeError, match="rt_cd=1"):
            kis_api._request("GET", "/test", tr_id="TEST", params={})

        # autouse fixture 가 FETCH_RETRY_MAX=2 로 설정 → 2회 호출
        assert mock_request.call_count == 2


# ---------------------------------------------------------------------------
# _safe_float
# ---------------------------------------------------------------------------


class TestSafeFloat:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("12.5", 12.5),
            ("0", 0.0),
            ("", None),
            ("-", None),
            (None, None),
            ("abc", None),
            (3.14, 3.14),
            (0, 0.0),
        ],
    )
    def test_converts_or_returns_none(self, value, expected):
        """KIS 응답 문자열을 안전하게 float 또는 None 으로 변환한다."""
        assert kis_api._safe_float(value) == expected


# ---------------------------------------------------------------------------
# fetch_minute_chart_chunk (TR FHKST03010230)
# ---------------------------------------------------------------------------


def _sample_minute_response(rows: list[tuple[str, str, float, float, float, float, float]]) -> dict:
    """KIS 일별 분봉 응답 더블.

    rows: [(YYYYMMDD, HHMMSS, open, high, low, close, volume), ...]
    명세 그대로 시간 역순(최신→과거) 으로 전달해야 함.
    """
    return {
        "rt_cd": "0",
        "msg_cd": "MCA00000",
        "msg1": "정상처리되었습니다.",
        "output1": {"hts_kor_isnm": "TEST", "stck_prpr": "100"},
        "output2": [
            {
                "stck_bsop_date": d,
                "stck_cntg_hour": h,
                "stck_prpr": str(c),
                "stck_oprc": str(o),
                "stck_hgpr": str(hi),
                "stck_lwpr": str(low),
                "cntg_vol": str(int(v)),
                "acml_tr_pbmn": "0",
            }
            for d, h, o, hi, low, c, v in rows
        ],
    }


class TestFetchMinuteChartChunk:
    def test_normalizes_and_sorts_ascending(self, monkeypatch):
        """KIS 시간 역순 응답을 시간 정순으로 정렬해 반환한다."""
        _seed_token_cache()
        mock_request = MagicMock(
            return_value=_make_response(
                _sample_minute_response([
                    # 시간 역순으로 전달 (KIS 형식)
                    ("20260108", "140000", 57300, 57400, 57200, 57300, 59047),
                    ("20260108", "135900", 57400, 57500, 57300, 57300, 118619),
                    ("20260108", "135800", 57400, 57400, 57300, 57400, 10000),
                ])
            )
        )
        monkeypatch.setattr(kis_api.httpx, "request", mock_request)

        df = kis_api.fetch_minute_chart_chunk(
            "005930", date(2026, 1, 8), hour_end="140000"
        )

        assert list(df.columns) == ["ticker", "datetime", "open", "high", "low", "close", "volume"]
        assert len(df) == 3
        # 시간 정순 정렬
        assert df.iloc[0]["datetime"].strftime("%H%M%S") == "135800"
        assert df.iloc[1]["datetime"].strftime("%H%M%S") == "135900"
        assert df.iloc[2]["datetime"].strftime("%H%M%S") == "140000"
        assert df.iloc[2]["close"] == 57300.0
        assert df.iloc[2]["volume"] == 59047.0

    def test_returns_empty_when_no_output(self, monkeypatch):
        """output2 가 빈 배열이면 빈 DataFrame."""
        _seed_token_cache()
        mock_request = MagicMock(
            return_value=_make_response(
                {"rt_cd": "0", "msg1": "정상", "output1": {}, "output2": []}
            )
        )
        monkeypatch.setattr(kis_api.httpx, "request", mock_request)

        df = kis_api.fetch_minute_chart_chunk("999999", date(2026, 1, 8))

        assert df.empty

    def test_passes_correct_params(self, monkeypatch):
        """params 가 명세서 그대로 전달되는지 확인."""
        _seed_token_cache()
        captured: dict = {}

        def fake_request(method, url, **kwargs):
            captured.update(kwargs.get("params", {}))
            return _make_response(_sample_minute_response([]))

        monkeypatch.setattr(kis_api.httpx, "request", fake_request)

        kis_api.fetch_minute_chart_chunk(
            "005930", date(2026, 1, 8), hour_end="140000", include_premarket=True
        )

        assert captured["FID_COND_MRKT_DIV_CODE"] == "J"
        assert captured["FID_INPUT_ISCD"] == "005930"
        assert captured["FID_INPUT_HOUR_1"] == "140000"
        assert captured["FID_INPUT_DATE_1"] == "20260108"
        assert captured["FID_PW_DATA_INCU_YN"] == "Y"
        assert captured["FID_FAKE_TICK_INCU_YN"] == ""

    @pytest.mark.parametrize("bad_hour", ["14:00", "1400", "1400000", "abcdef", ""])
    def test_invalid_hour_end_raises(self, bad_hour: str) -> None:
        """hour_end 가 6자리 숫자가 아니면 ValueError."""
        with pytest.raises(ValueError):
            kis_api.fetch_minute_chart_chunk(
                "005930", date(2026, 1, 8), hour_end=bad_hour
            )

    def test_skips_rows_with_invalid_time(self, monkeypatch):
        """stck_cntg_hour 가 비정상이면 그 행만 스킵."""
        _seed_token_cache()
        mock_request = MagicMock(
            return_value=_make_response({
                "rt_cd": "0", "msg1": "정상",
                "output1": {},
                "output2": [
                    {"stck_bsop_date": "20260108", "stck_cntg_hour": "140000",
                     "stck_oprc": "100", "stck_hgpr": "100", "stck_lwpr": "100",
                     "stck_prpr": "100", "cntg_vol": "1", "acml_tr_pbmn": "0"},
                    {"stck_bsop_date": "20260108", "stck_cntg_hour": "999999",  # 비정상
                     "stck_oprc": "100", "stck_hgpr": "100", "stck_lwpr": "100",
                     "stck_prpr": "100", "cntg_vol": "1", "acml_tr_pbmn": "0"},
                    {"stck_bsop_date": "", "stck_cntg_hour": "135800",  # 빈 날짜
                     "stck_oprc": "100", "stck_hgpr": "100", "stck_lwpr": "100",
                     "stck_prpr": "100", "cntg_vol": "1", "acml_tr_pbmn": "0"},
                ],
            })
        )
        monkeypatch.setattr(kis_api.httpx, "request", mock_request)

        df = kis_api.fetch_minute_chart_chunk("005930", date(2026, 1, 8))

        # 정상 1개만 남음
        assert len(df) == 1
        assert df.iloc[0]["datetime"].strftime("%H%M%S") == "140000"
