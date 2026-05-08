"""한국(KOSPI200) 종목 유니버스 갱신 (KIS 종목 마스터 기반).

주요 함수:
    update_kospi200 : KIS 마스터에서 KOSPI200 구성종목을 추출해 DB 갱신
"""
from __future__ import annotations

from loguru import logger

from scanner.db.session import get_session
from scanner.db.universe_db import _upsert_tickers
from scanner.kr.kis_master import fetch_kospi200_constituents


def update_kospi200() -> int:
    """KIS 종목 마스터에서 KOSPI200 구성종목을 가져와 Universe 테이블을 갱신한다.

    Returns:
        upsert 된 종목 수 (멤버십 정보 부재로 0 종목이면 0 반환).
    """
    logger.info("KOSPI200 구성종목 갱신 시작 (소스: KIS 종목 마스터)")
    df = fetch_kospi200_constituents()

    if df.empty:
        logger.warning("KOSPI200 구성종목이 비어있습니다 (KIS 마스터 갱신 지연 가능).")
        return 0

    rows: list[dict] = [
        {
            "ticker": str(row["ticker"]),
            "name": str(row["name"]),
            "sector": row.get("sector"),
        }
        for _, row in df.iterrows()
    ]

    with get_session() as sess:
        count = _upsert_tickers(rows, "KR", sess)

    logger.info("KOSPI200 {}종목 upsert 완료", count)
    return count
