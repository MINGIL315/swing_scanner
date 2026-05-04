"""미국 주식 데이터 수집기 (yfinance 기반).

yfinance 세션 재사용 + 최대 3회 exponential backoff 재시도.

주요 함수:
    fetch_us_daily       : 일봉 OHLCV
    fetch_us_weekly      : 주봉 OHLCV
    fetch_us_intraday    : 60분봉 OHLCV (최근 60일 한정 — yfinance 제약)
    fetch_us_fundamental : EPS/PER/PBR/시가총액
"""
from __future__ import annotations

import time
from datetime import date, timedelta

import pandas as pd
from loguru import logger

from scanner.config import (
    FETCH_RETRY_BACKOFF_BASE,
    FETCH_RETRY_MAX,
    FETCH_TIMEOUT_SECONDS,
)

try:
    import yfinance as yf  # type: ignore[import]
    _YFINANCE_AVAILABLE = True
except ImportError:  # pragma: no cover
    _YFINANCE_AVAILABLE = False


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------


def _require_yfinance() -> None:
    if not _YFINANCE_AVAILABLE:
        raise RuntimeError("yfinance가 설치되지 않았습니다.")


def _ticker_obj(ticker: str) -> "yf.Ticker":
    return yf.Ticker(ticker)


def _retry_download(
    fn,
    *args,
    max_attempts: int = FETCH_RETRY_MAX,
    **kwargs,
) -> pd.DataFrame:
    """fn(*args, **kwargs) 를 최대 max_attempts 회 재시도한다."""
    for attempt in range(max_attempts):
        try:
            df: pd.DataFrame = fn(*args, **kwargs)
            if df is not None and not df.empty:
                return df
            logger.debug("빈 응답 (attempt {}/{})", attempt + 1, max_attempts)
        except Exception as exc:
            logger.warning(
                "fetch 오류 (attempt {}/{}): {}", attempt + 1, max_attempts, exc
            )

        if attempt < max_attempts - 1:
            backoff = FETCH_RETRY_BACKOFF_BASE ** (attempt + 1)
            time.sleep(backoff)

    return pd.DataFrame()


def _normalize_yf_ohlcv(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """yfinance OHLCV DataFrame을 통일된 형태로 변환한다.

    yfinance 반환 컬럼: Open, High, Low, Close, Volume (대문자)
    → open, high, low, close, volume
    날짜 인덱스 → date 컬럼
    """
    df = df.copy()

    # MultiIndex 컬럼 (yfinance 0.2.x 에서 발생 가능)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    rename_map = {
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
        "Dividends": "dividends",
        "Stock Splits": "stock_splits",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    df.index.name = "date"
    df = df.reset_index()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df.insert(0, "ticker", ticker)
    return df


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------


def fetch_us_daily(
    ticker: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    """yfinance로 일봉 OHLCV를 가져온다.

    Args:
        ticker: Yahoo Finance 티커 (예: "AAPL", "BRK-B").
        start : 조회 시작일.
        end   : 조회 종료일.

    Returns:
        columns = [ticker, date, open, high, low, close, volume]
        실패 시 빈 DataFrame.
    """
    _require_yfinance()
    logger.debug("US daily fetch: {} {} ~ {}", ticker, start, end)

    t = _ticker_obj(ticker)
    df = _retry_download(
        t.history,
        start=str(start),
        end=str(end + timedelta(days=1)),  # yfinance end는 exclusive
        interval="1d",
        auto_adjust=True,
        timeout=int(FETCH_TIMEOUT_SECONDS),
    )

    if df.empty:
        logger.warning("US daily 빈 결과: {}", ticker)
        return pd.DataFrame()

    df = _normalize_yf_ohlcv(df, ticker)
    keep = [c for c in ["ticker", "date", "open", "high", "low", "close", "volume"] if c in df.columns]
    return df[keep]


def fetch_us_weekly(
    ticker: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    """yfinance로 주봉 OHLCV를 가져온다.

    Args:
        ticker: Yahoo Finance 티커.
        start : 조회 시작일.
        end   : 조회 종료일.

    Returns:
        columns = [ticker, week_start_date, open, high, low, close, volume]
    """
    _require_yfinance()
    logger.debug("US weekly fetch: {} {} ~ {}", ticker, start, end)

    t = _ticker_obj(ticker)
    df = _retry_download(
        t.history,
        start=str(start),
        end=str(end + timedelta(days=1)),
        interval="1wk",
        auto_adjust=True,
        timeout=int(FETCH_TIMEOUT_SECONDS),
    )

    if df.empty:
        logger.warning("US weekly 빈 결과: {}", ticker)
        return pd.DataFrame()

    df = _normalize_yf_ohlcv(df, ticker)
    df = df.rename(columns={"date": "week_start_date"})
    keep = [c for c in ["ticker", "week_start_date", "open", "high", "low", "close", "volume"] if c in df.columns]
    return df[keep]


def fetch_us_intraday(
    ticker: str,
    target_date: date,
) -> pd.DataFrame:
    """yfinance로 60분봉 OHLCV를 가져온다.

    yfinance는 60분봉 히스토리를 최근 730일까지 제공한다 (interval="60m").
    단, 요청 범위가 너무 좁으면 빈 결과가 올 수 있으므로
    target_date 기준 ±2일 범위로 요청한 뒤 해당 날짜만 필터링한다.

    Args:
        ticker     : Yahoo Finance 티커.
        target_date: 조회 날짜.

    Returns:
        columns = [ticker, datetime, open, high, low, close, volume]
    """
    _require_yfinance()
    logger.debug("US intraday fetch: {} date={}", ticker, target_date)

    fetch_start = target_date - timedelta(days=2)
    fetch_end = target_date + timedelta(days=2)

    t = _ticker_obj(ticker)
    df = _retry_download(
        t.history,
        start=str(fetch_start),
        end=str(fetch_end),
        interval="60m",
        auto_adjust=True,
        timeout=int(FETCH_TIMEOUT_SECONDS),
    )

    if df.empty:
        logger.warning("US intraday 빈 결과: {} date={}", ticker, target_date)
        return pd.DataFrame()

    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    rename_map = {
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
    df.index.name = "datetime"
    df = df.reset_index()
    df["datetime"] = pd.to_datetime(df["datetime"])

    # target_date 당일 데이터만
    df = df[df["datetime"].dt.date == target_date]
    df.insert(0, "ticker", ticker)

    keep = [c for c in ["ticker", "datetime", "open", "high", "low", "close", "volume"] if c in df.columns]
    return df[keep].reset_index(drop=True)


def fetch_us_fundamental(ticker: str) -> pd.DataFrame:
    """yfinance Ticker.info 에서 재무 지표를 가져온다.

    PER(trailingPE), PBR(priceToBook), 시가총액(marketCap)을 파싱한다.
    (부채비율은 yfinance info에 없으므로 balance_sheet 활용 — 현재 STEP에서는 생략)

    Args:
        ticker: Yahoo Finance 티커.

    Returns:
        columns = [ticker, date, per, pbr]
        단일 행 (오늘 날짜 스냅샷).
    """
    _require_yfinance()
    logger.debug("US fundamental fetch: {}", ticker)

    today = date.today()

    def _get_info() -> dict:
        return _ticker_obj(ticker).info

    try:
        info: dict = {}
        for attempt in range(FETCH_RETRY_MAX):
            try:
                info = _get_info()
                if info:
                    break
            except Exception as exc:
                logger.warning(
                    "fundamental info 오류 (attempt {}/{}): {}", attempt + 1, FETCH_RETRY_MAX, exc
                )
                if attempt < FETCH_RETRY_MAX - 1:
                    time.sleep(FETCH_RETRY_BACKOFF_BASE ** (attempt + 1))

        if not info:
            return pd.DataFrame()

        row = {
            "ticker": ticker,
            "date": today,
            "per": info.get("trailingPE") or info.get("forwardPE"),
            "pbr": info.get("priceToBook"),
        }
        return pd.DataFrame([row])

    except Exception as exc:
        logger.error("US fundamental fetch 실패 {}: {}", ticker, exc)
        return pd.DataFrame()
