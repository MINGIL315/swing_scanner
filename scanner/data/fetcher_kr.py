"""한국 주식 데이터 수집기 (pykrx 기반).

pykrx API 호출마다 0.2초 지연 + 최대 3회 exponential backoff 재시도를 적용해
KRX 서버 부하를 방지하고 간헐적 실패를 복구한다.

주요 함수:
    fetch_kr_daily       : 일봉 OHLCV
    fetch_kr_weekly      : 주봉 OHLCV (일봉을 리샘플)
    fetch_kr_intraday    : 60분봉 OHLCV
    fetch_kr_fundamental : PER/PBR/ROE/시가총액
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta

import pandas as pd
from loguru import logger

from scanner.config import (
    FETCH_RETRY_BACKOFF_BASE,
    FETCH_RETRY_MAX,
)

try:
    from pykrx import stock as krx_stock  # type: ignore[import]
    _PYKRX_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PYKRX_AVAILABLE = False


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------

_RATE_LIMIT_SECONDS: float = 0.2  # KRX 요청 간격


def _require_pykrx() -> None:
    if not _PYKRX_AVAILABLE:
        raise RuntimeError("pykrx가 설치되지 않았습니다.")


def _date_str(d: date) -> str:
    return d.strftime("%Y%m%d")


def _retry_call(fn, *args, **kwargs) -> pd.DataFrame:
    """fn(*args, **kwargs) 를 최대 FETCH_RETRY_MAX 회 재시도한다.

    빈 DataFrame이 반환되거나 예외가 발생하면 재시도한다.
    모든 시도 실패 시 빈 DataFrame 반환.
    """
    for attempt in range(FETCH_RETRY_MAX):
        try:
            time.sleep(_RATE_LIMIT_SECONDS)
            df: pd.DataFrame = fn(*args, **kwargs)
            if df is not None and not df.empty:
                return df
            logger.debug(
                "빈 응답 (attempt {}/{}) fn={}", attempt + 1, FETCH_RETRY_MAX, fn.__name__
            )
        except Exception as exc:
            logger.warning(
                "fetch 오류 (attempt {}/{}) fn={}: {}",
                attempt + 1,
                FETCH_RETRY_MAX,
                fn.__name__,
                exc,
            )

        if attempt < FETCH_RETRY_MAX - 1:
            backoff = FETCH_RETRY_BACKOFF_BASE ** (attempt + 1)
            logger.debug("{}초 후 재시도", backoff)
            time.sleep(backoff)

    return pd.DataFrame()


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """pykrx OHLCV 컬럼명을 통일한다.

    pykrx 반환 컬럼: 시가, 고가, 저가, 종가, 거래량, 거래대금 (한글)
    → open, high, low, close, volume, value
    """
    rename_map = {
        "시가": "open",
        "고가": "high",
        "저가": "low",
        "종가": "close",
        "거래량": "volume",
        "거래대금": "value",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
    # 인덱스(날짜)를 'date' 컬럼으로
    df.index.name = "date"
    df = df.reset_index()
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------


def fetch_kr_daily(
    ticker: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    """pykrx로 일봉 OHLCV를 가져온다.

    Args:
        ticker: 종목 코드 (예: "005930").
        start : 조회 시작일.
        end   : 조회 종료일.

    Returns:
        columns = [date, open, high, low, close, volume, value]
        실패 시 빈 DataFrame.
    """
    _require_pykrx()
    logger.debug("KR daily fetch: {} {} ~ {}", ticker, start, end)

    df = _retry_call(
        krx_stock.get_market_ohlcv_by_date,
        _date_str(start),
        _date_str(end),
        ticker,
    )
    if df.empty:
        logger.warning("KR daily 빈 결과: {}", ticker)
        return pd.DataFrame()

    df = _normalize_ohlcv(df)
    df.insert(0, "ticker", ticker)
    return df[[c for c in ["ticker", "date", "open", "high", "low", "close", "volume", "value"] if c in df.columns]]


def fetch_kr_weekly(
    ticker: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    """일봉을 주봉으로 리샘플해 반환한다.

    Args:
        ticker: 종목 코드.
        start : 조회 시작일 (충분한 선행 데이터를 위해 여유 있게 지정 권장).
        end   : 조회 종료일.

    Returns:
        columns = [ticker, week_start_date, open, high, low, close, volume, value]
    """
    # 주봉 생성을 위해 최소 1주 앞 데이터 확보
    adjusted_start = start - timedelta(days=7)
    df_daily = fetch_kr_daily(ticker, adjusted_start, end)
    if df_daily.empty:
        return pd.DataFrame()

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

    df_w = df_daily[list(agg.keys())].resample("W-MON", label="left", closed="left").agg(agg)
    df_w = df_w.dropna(how="all").reset_index()
    df_w = df_w.rename(columns={"date": "week_start_date"})
    df_w["week_start_date"] = df_w["week_start_date"].dt.date
    df_w.insert(0, "ticker", ticker)
    return df_w


def fetch_kr_intraday(
    ticker: str,
    target_date: date,
) -> pd.DataFrame:
    """단일 날짜의 60분봉 OHLCV를 가져온다.

    pykrx `get_market_ohlcv_by_ticker` 는 분봉을 직접 제공하지 않는다.
    대신 `get_market_trading_volume_by_date` 또는 `naver_finance` 방식을
    사용해야 하나, STEP 2 에서는 pykrx의 분봉 API가 제한적이므로
    빈 DataFrame을 반환하고 STEP 3+ 에서 별도 확장한다.

    Returns:
        columns = [ticker, datetime, open, high, low, close, volume]
        현재 pykrx 제약으로 항상 빈 DataFrame 반환 — 추후 구현.
    """
    logger.debug(
        "KR intraday fetch 미구현 (pykrx 분봉 제한): ticker={} date={}",
        ticker,
        target_date,
    )
    # pykrx는 공식적으로 분봉 API를 제공하지 않음 — placeholder
    return pd.DataFrame(
        columns=["ticker", "datetime", "open", "high", "low", "close", "volume"]
    )


def fetch_kr_fundamental(
    ticker: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    """pykrx로 PER/PBR/ROE/시가총액 일별 스냅샷을 가져온다.

    Args:
        ticker: 종목 코드.
        start : 조회 시작일.
        end   : 조회 종료일.

    Returns:
        columns = [ticker, date, per, pbr, roe, market_cap]
    """
    _require_pykrx()
    logger.debug("KR fundamental fetch: {} {} ~ {}", ticker, start, end)

    df = _retry_call(
        krx_stock.get_market_fundamental_by_date,
        _date_str(start),
        _date_str(end),
        ticker,
    )
    if df.empty:
        logger.warning("KR fundamental 빈 결과: {}", ticker)
        return pd.DataFrame()

    # pykrx 반환 컬럼: BPS, PER, PBR, EPS, DIV, DPS (한글 없음)
    rename_map = {
        "PER": "per",
        "PBR": "pbr",
        "ROE": "roe",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
    df.index.name = "date"
    df = df.reset_index()
    df["date"] = pd.to_datetime(df["date"]).dt.date

    # 시가총액은 별도 API
    cap_df = _retry_call(
        krx_stock.get_market_cap_by_date,
        _date_str(start),
        _date_str(end),
        ticker,
    )
    if not cap_df.empty:
        cap_df.index.name = "date"
        cap_df = cap_df.reset_index()
        cap_df["date"] = pd.to_datetime(cap_df["date"]).dt.date
        if "시가총액" in cap_df.columns:
            cap_df = cap_df.rename(columns={"시가총액": "market_cap"})
            df = df.merge(cap_df[["date", "market_cap"]], on="date", how="left")

    keep_cols = [c for c in ["ticker", "date", "per", "pbr", "roe", "market_cap"] if c in df.columns or c == "ticker"]
    df.insert(0, "ticker", ticker)
    df = df[[c for c in keep_cols if c in df.columns]]
    return df
