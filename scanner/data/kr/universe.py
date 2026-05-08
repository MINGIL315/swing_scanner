"""한국(KOSPI200) 종목 유니버스 갱신.

주요 함수:
    update_kospi200 : KRX에서 KOSPI200 구성종목을 가져와 DB 갱신
"""
from __future__ import annotations

import time
from datetime import date

import pandas as pd
from loguru import logger

from scanner.data.universe import _upsert_tickers
from scanner.db.session import get_session

# pykrx는 선택적 임포트 (네트워크 없는 환경에서도 import 자체는 성공)
try:
    from pykrx import stock as krx_stock  # type: ignore[import]
    _PYKRX_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PYKRX_AVAILABLE = False
    logger.warning("pykrx 미설치 — 한국 종목 데이터 취득 불가")


def _today_str() -> str:
    return date.today().strftime("%Y%m%d")


def update_kospi200() -> int:
    """KRX에서 KOSPI200 구성종목을 가져와 Universe 테이블을 갱신한다.

    Returns:
        갱신(upsert)된 종목 수
    """
    if not _PYKRX_AVAILABLE:
        raise RuntimeError("pykrx가 설치되지 않았습니다.")

    today = _today_str()
    logger.info("KOSPI200 구성종목 조회 시작 (기준일: {})", today)

    # pykrx: 날짜 기준 KOSPI200 종목 코드 목록
    # 오류 시 빈 DataFrame이 반환될 수 있으므로 타입을 먼저 확인한다.
    _raw = krx_stock.get_index_portfolio_deposit_file("1028", today)
    if isinstance(_raw, pd.DataFrame):
        tickers: list[str] = [] if _raw.empty else _raw.iloc[:, 0].astype(str).tolist()
    elif isinstance(_raw, list):
        tickers = _raw
    else:
        tickers = list(_raw) if _raw else []

    if not tickers:
        logger.warning("KOSPI200 종목 목록이 비어있습니다 (휴장일 가능성).")
        return 0

    rows: list[dict] = []
    for ticker in tickers:
        try:
            name = krx_stock.get_market_ticker_name(ticker)
            rows.append({"ticker": ticker, "name": name or ticker, "sector": None})
            time.sleep(0.05)  # KRX 부하 방지
        except Exception as exc:
            logger.warning("티커 {} 이름 조회 실패: {}", ticker, exc)
            rows.append({"ticker": ticker, "name": ticker, "sector": None})

    with get_session() as sess:
        count = _upsert_tickers(rows, "KR", sess)

    logger.info("KOSPI200 {} 종목 upsert 완료", count)
    return count
