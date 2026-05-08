"""미국(S&P500) 종목 유니버스 갱신.

주요 함수:
    update_sp500 : Wikipedia에서 S&P500 구성종목을 가져와 DB 갱신
"""
from __future__ import annotations

import pandas as pd
import requests
from loguru import logger

from scanner.data.universe import _upsert_tickers
from scanner.db.session import get_session

# Wikipedia S&P500 목록 URL
_SP500_WIKI_URL = (
    "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
)


def update_sp500() -> int:
    """Wikipedia에서 S&P500 구성종목을 스크래핑해 Universe 테이블을 갱신한다.

    Returns:
        갱신(upsert)된 종목 수
    """
    logger.info("S&P500 구성종목 스크래핑 시작 ({})", _SP500_WIKI_URL)

    try:
        resp = requests.get(
            _SP500_WIKI_URL,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SwingScanner/1.0)"},
            timeout=15,
        )
        resp.raise_for_status()
        tables: list[pd.DataFrame] = pd.read_html(
            resp.text,
            attrs={"id": "constituents"},
        )
        df = tables[0]
    except Exception as exc:
        logger.error("S&P500 Wikipedia 스크래핑 실패: {}", exc)
        raise

    # 컬럼명 정규화 (Wikipedia 표 구조가 바뀔 수 있음)
    col_map = {
        c: c.strip().lower().replace(" ", "_") for c in df.columns
    }
    df = df.rename(columns=col_map)

    # 필수 컬럼 확인
    symbol_col = next(
        (c for c in df.columns if "symbol" in c or "ticker" in c), None
    )
    name_col = next(
        (c for c in df.columns if "security" in c or "name" in c or "company" in c),
        None,
    )
    sector_col = next(
        (c for c in df.columns if "gics_sector" in c or "sector" in c), None
    )

    if symbol_col is None or name_col is None:
        raise ValueError(
            f"Wikipedia 표 컬럼 파싱 실패. 컬럼 목록: {list(df.columns)}"
        )

    rows: list[dict] = []
    for _, r in df.iterrows():
        ticker = str(r[symbol_col]).strip().replace(".", "-")  # BRK.B → BRK-B
        name = str(r[name_col]).strip()
        sector = str(r[sector_col]).strip() if sector_col else None
        rows.append({"ticker": ticker, "name": name, "sector": sector})

    with get_session() as sess:
        count = _upsert_tickers(rows, "US", sess)

    logger.info("S&P500 {} 종목 upsert 완료", count)
    return count
