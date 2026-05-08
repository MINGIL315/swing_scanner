"""한국(KOSPI/KOSDAQ) 주식 데이터 수집기 (KIS OpenAPI 기반).

``scanner.kr.kis_api`` 의 클라이언트를 호출하여 일봉/재무를 표준 형식으로 반환한다.
주봉은 일봉을 리샘플하여 만든다 (KIS 의 W 응답 의미가 주의 시작/끝 중 어느 쪽인지
명세에 명시되지 않아, 의미 명확한 일봉 리샘플 방식을 채택).

호출처(``data_pipeline`` 등) 는 옛 ``fetch_daily(ticker, start, end)`` /
``fetch_weekly(ticker, start, end)`` 시그니처를 그대로 사용한다.
``fetch_fundamental`` 만 US 모듈과 동일하게 ``(ticker)`` 단일 인자로 통일.

주요 함수:
    fetch_daily       : 일봉 OHLCV
    fetch_weekly      : 주봉 OHLCV (일봉 리샘플)
    fetch_intraday    : 60분봉 OHLCV (placeholder — 운영 미사용)
    fetch_fundamental : 부채비율 + ROE 단일 스냅샷 (KIS 재무비율 API)
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from loguru import logger

from scanner.kr import kis_api


# ---------------------------------------------------------------------------
# 일봉
# ---------------------------------------------------------------------------


def fetch_daily(
    ticker: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    """KIS API 로 일봉 OHLCV 를 가져온다.

    Args:
        ticker: 6자리 종목 코드 (예: "005930").
        start : 조회 시작일.
        end   : 조회 종료일.

    Returns:
        columns = [ticker, date, open, high, low, close, volume, value]
        실패/빈 결과 시 빈 DataFrame.
    """
    logger.debug("KR daily fetch: {} {} ~ {}", ticker, start, end)
    df = kis_api.fetch_daily_chart(ticker, start, end, period_div_code="D")
    if df.empty:
        logger.warning("KR daily 빈 결과: {}", ticker)
    return df


# ---------------------------------------------------------------------------
# 주봉 (일봉 리샘플)
# ---------------------------------------------------------------------------


def fetch_weekly(
    ticker: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    """일봉을 주봉(W-MON, label=left)으로 리샘플하여 반환한다.

    Args:
        ticker: 종목 코드.
        start : 조회 시작일. 주봉 정렬을 위해 내부에서 7일 앞으로 확장.
        end   : 조회 종료일.

    Returns:
        columns = [ticker, week_start_date, open, high, low, close, volume, value]
    """
    adjusted_start = start - timedelta(days=7)
    df_daily = fetch_daily(ticker, adjusted_start, end)
    if df_daily.empty:
        return pd.DataFrame()

    df_daily = df_daily.copy()
    df_daily["date"] = pd.to_datetime(df_daily["date"])
    df_daily = df_daily.set_index("date")

    agg: dict[str, str] = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    if "value" in df_daily.columns:
        agg["value"] = "sum"

    df_w = (
        df_daily[list(agg.keys())]
        .resample("W-MON", label="left", closed="left")
        .agg(agg)
        .dropna(how="all")
        .reset_index()
        .rename(columns={"date": "week_start_date"})
    )
    df_w["week_start_date"] = df_w["week_start_date"].dt.date
    df_w.insert(0, "ticker", ticker)
    return df_w


# ---------------------------------------------------------------------------
# 60분봉 (운영 미사용 placeholder)
# ---------------------------------------------------------------------------


def fetch_intraday(
    ticker: str,
    target_date: date,
) -> pd.DataFrame:
    """단일 날짜의 60분봉 OHLCV 를 반환한다 (현재 placeholder).

    운영 코드 (data_pipeline / scanner / cli) 에서 호출되지 않으며
    KIS 분봉 API 실구현은 Phase C 에서 도입 예정.

    Returns:
        빈 DataFrame (columns = [ticker, datetime, open, high, low, close, volume]).
    """
    logger.debug("KR intraday placeholder: {} {}", ticker, target_date)
    return pd.DataFrame(
        columns=["ticker", "datetime", "open", "high", "low", "close", "volume"]
    )


# ---------------------------------------------------------------------------
# 재무 (단일 스냅샷)
# ---------------------------------------------------------------------------


def fetch_fundamental(ticker: str) -> pd.DataFrame:
    """KIS 재무비율의 최신 결산 1행을 단일 스냅샷으로 반환한다.

    KIS API 응답에서 분석에 사용하는 두 지표만 추출:
        - ``debt_ratio`` (부채비율) — KR 재무 필터의 ``< 200%`` 조건
        - ``roe``        — 분석 미사용이지만 DB 모델에 컬럼 존재, 기록용

    PER/PBR 은 KIS 재무비율 API 응답에 없고 분석에서도 사용하지 않으므로
    수집하지 않는다 (PER 적자 컷 필터는 폐기됨 — 2026-05-08).

    Args:
        ticker: 6자리 종목코드.

    Returns:
        columns = [ticker, date, debt_ratio, roe]
        실패/빈 결과 시 빈 DataFrame.
    """
    logger.debug("KR fundamental fetch: {}", ticker)
    df = kis_api.fetch_financial_ratio(ticker, annual=True)
    if df.empty:
        logger.warning("KR fundamental 빈 결과: {}", ticker)
        return df

    keep = [c for c in ("ticker", "date", "debt_ratio", "roe") if c in df.columns]
    return df[keep]
