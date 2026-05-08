"""통합 데이터 수집 파이프라인.

ThreadPoolExecutor(max_workers=5) 로 종목을 병렬 fetch 하고
Rich 진행 표시줄로 상태를 출력한다.
같은 날 이미 수집된 데이터는 스킵(skip-if-same-day).
실패 종목은 logs/failed_fetches_YYYY-MM-DD.json 에 누적 기록한다.

주요 함수:
    fetch_all_ohlcv        : 모든 활성 종목 OHLCV 일괄 수집
    fetch_all_fundamentals : 모든 활성 종목 재무 일괄 수집
    run_data_pipeline      : OHLCV + 재무 순차 실행
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from loguru import logger
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
)
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from scanner.config import FETCH_MAX_WORKERS, OHLCV_LOOKBACK_DAYS, settings
from scanner.kr import fetcher as kr_fetcher
from scanner.us import fetcher as us_fetcher
from scanner.db.universe_db import get_active_tickers
from scanner.db.models import Fundamental, OHLCVDaily, OHLCVWeekly, Universe
from scanner.db.session import get_session

console = Console()


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------


def _failed_log_path(target_date: date) -> Path:
    settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
    return settings.LOG_DIR / f"failed_fetches_{target_date.isoformat()}.json"


def _append_failed(target_date: date, ticker: str, reason: str) -> None:
    path = _failed_log_path(target_date)
    existing: list[dict] = []
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            existing = []
    existing.append({"ticker": ticker, "reason": reason, "date": target_date.isoformat()})
    path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_market(ticker: str) -> str:
    """Universe 테이블에서 market 코드를 조회한다."""
    with get_session() as sess:
        row = sess.execute(
            select(Universe.market).where(Universe.ticker == ticker)
        ).scalar_one_or_none()
    return row or "KR"


def _latest_ohlcv_date(ticker: str) -> date | None:
    """ohlcv_daily 에 저장된 가장 최근 날짜를 반환한다."""
    with get_session() as sess:
        from sqlalchemy import func as sa_func
        result = sess.execute(
            select(sa_func.max(OHLCVDaily.date)).where(OHLCVDaily.ticker == ticker)
        ).scalar_one_or_none()
    return result


def _upsert_ohlcv_daily(rows: list[dict]) -> None:
    if not rows:
        return
    with get_session() as sess:
        for row in rows:
            stmt = (
                sqlite_insert(OHLCVDaily)
                .values(**row)
                .on_conflict_do_update(
                    index_elements=["ticker", "date"],
                    set_={k: row[k] for k in row if k not in ("id",)},
                )
            )
            sess.execute(stmt)


def _upsert_ohlcv_weekly(rows: list[dict]) -> None:
    if not rows:
        return
    with get_session() as sess:
        for row in rows:
            stmt = (
                sqlite_insert(OHLCVWeekly)
                .values(**row)
                .on_conflict_do_update(
                    index_elements=["ticker", "week_start_date"],
                    set_={k: row[k] for k in row if k not in ("id",)},
                )
            )
            sess.execute(stmt)


def _upsert_fundamental(rows: list[dict]) -> None:
    if not rows:
        return
    with get_session() as sess:
        for row in rows:
            stmt = (
                sqlite_insert(Fundamental)
                .values(**row)
                .on_conflict_do_update(
                    index_elements=["ticker", "date"],
                    set_={k: row[k] for k in row if k not in ("id",)},
                )
            )
            sess.execute(stmt)


def _df_to_dicts(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    return df.where(pd.notna(df), other=None).to_dict(orient="records")


# ---------------------------------------------------------------------------
# 단일 종목 fetch
# ---------------------------------------------------------------------------


def _fetch_ohlcv_one(
    ticker: str,
    market: str,
    start: date,
    end: date,
) -> tuple[str, bool, str]:
    """단일 종목 OHLCV를 fetch 후 DB에 저장한다.

    Returns:
        (ticker, success, error_message)
    """
    try:
        if market == "KR":
            df_d = kr_fetcher.fetch_daily(ticker, start, end)
            df_w = kr_fetcher.fetch_weekly(ticker, start, end)
        else:
            df_d = us_fetcher.fetch_daily(ticker, start, end)
            df_w = us_fetcher.fetch_weekly(ticker, start, end)

        _upsert_ohlcv_daily(_df_to_dicts(df_d))
        _upsert_ohlcv_weekly(_df_to_dicts(df_w))
        return ticker, True, ""
    except Exception as exc:
        msg = str(exc)
        logger.error("OHLCV fetch 실패 {}: {}", ticker, msg)
        return ticker, False, msg


def _fetch_fundamental_one(
    ticker: str,
    market: str,
    target_date: date,
) -> tuple[str, bool, str]:
    """단일 종목 재무를 fetch 후 DB에 저장한다."""
    try:
        if market == "KR":
            df = kr_fetcher.fetch_fundamental(ticker)
        else:
            df = us_fetcher.fetch_fundamental(ticker)

        _upsert_fundamental(_df_to_dicts(df))
        return ticker, True, ""
    except Exception as exc:
        msg = str(exc)
        logger.error("Fundamental fetch 실패 {}: {}", ticker, msg)
        return ticker, False, msg


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------


def fetch_all_ohlcv(
    market: str = "ALL",
    start: date | None = None,
    end: date | None = None,
) -> dict[str, int]:
    """모든 활성 종목의 OHLCV를 병렬 수집한다.

    Args:
        market : "KR", "US", "ALL".
        start  : 수집 시작일. None 이면 오늘 기준 1년 전.
        end    : 수집 종료일. None 이면 오늘.

    Returns:
        {"success": N, "failed": M, "skipped": K}
    """
    today = date.today()
    end = end or today
    start = start or (today - timedelta(days=OHLCV_LOOKBACK_DAYS))

    tickers = get_active_tickers(market)  # type: ignore[arg-type]
    if not tickers:
        logger.warning("활성 종목이 없습니다. 먼저 update-universe 를 실행하세요.")
        return {"success": 0, "failed": 0, "skipped": 0}

    logger.info("OHLCV 수집 시작: {} 종목, {} ~ {}", len(tickers), start, end)

    success_count = 0
    failed_count = 0
    skipped_count = 0

    # 종목별 market 캐시 (DB 쿼리 최소화)
    with get_session() as sess:
        market_map: dict[str, str] = {
            row.ticker: row.market
            for row in sess.execute(
                select(Universe.ticker, Universe.market).where(Universe.is_active.is_(True))
            ).all()
        }

    tasks = []
    for ticker in tickers:
        last_date = _latest_ohlcv_date(ticker)
        if last_date is not None and last_date >= end:
            skipped_count += 1
            continue
        effective_start = (last_date + timedelta(days=1)) if last_date else start
        mk = market_map.get(ticker, "KR")
        tasks.append((ticker, mk, effective_start, end))

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=True,
    ) as progress:
        task_id = progress.add_task("OHLCV 수집 중...", total=len(tasks))

        with ThreadPoolExecutor(max_workers=FETCH_MAX_WORKERS) as executor:
            futures = {
                executor.submit(_fetch_ohlcv_one, t, mk, s, e): t
                for t, mk, s, e in tasks
            }
            for future in as_completed(futures):
                ticker_done, ok, err = future.result()
                if ok:
                    success_count += 1
                else:
                    failed_count += 1
                    _append_failed(today, ticker_done, err)
                progress.advance(task_id)

    logger.info(
        "OHLCV 수집 완료 — 성공: {}, 실패: {}, 스킵: {}",
        success_count, failed_count, skipped_count,
    )
    return {"success": success_count, "failed": failed_count, "skipped": skipped_count}


def fetch_all_fundamentals(
    market: str = "ALL",
    target_date: date | None = None,
) -> dict[str, int]:
    """모든 활성 종목의 재무 지표를 병렬 수집한다.

    Args:
        market     : "KR", "US", "ALL".
        target_date: 조회 기준일. None 이면 오늘.

    Returns:
        {"success": N, "failed": M}
    """
    today = target_date or date.today()
    tickers = get_active_tickers(market)  # type: ignore[arg-type]
    if not tickers:
        logger.warning("활성 종목이 없습니다.")
        return {"success": 0, "failed": 0}

    logger.info("재무 수집 시작: {} 종목 (기준일: {})", len(tickers), today)

    with get_session() as sess:
        market_map: dict[str, str] = {
            row.ticker: row.market
            for row in sess.execute(
                select(Universe.ticker, Universe.market).where(Universe.is_active.is_(True))
            ).all()
        }

    success_count = 0
    failed_count = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=True,
    ) as progress:
        task_id = progress.add_task("재무 수집 중...", total=len(tickers))

        with ThreadPoolExecutor(max_workers=FETCH_MAX_WORKERS) as executor:
            futures = {
                executor.submit(
                    _fetch_fundamental_one,
                    ticker,
                    market_map.get(ticker, "KR"),
                    today,
                ): ticker
                for ticker in tickers
            }
            for future in as_completed(futures):
                ticker_done, ok, err = future.result()
                if ok:
                    success_count += 1
                else:
                    failed_count += 1
                    _append_failed(today, ticker_done, err)
                progress.advance(task_id)

    logger.info(
        "재무 수집 완료 — 성공: {}, 실패: {}", success_count, failed_count
    )
    return {"success": success_count, "failed": failed_count}


def run_data_pipeline(
    market: str = "ALL",
    start: date | None = None,
    end: date | None = None,
) -> None:
    """OHLCV → 재무 순서로 전체 데이터 파이프라인을 실행한다.

    Args:
        market: "KR", "US", "ALL".
        start : OHLCV 수집 시작일.
        end   : OHLCV 수집 종료일.
    """
    console.print("[bold cyan]== 데이터 파이프라인 시작 ==[/bold cyan]")
    ohlcv_result = fetch_all_ohlcv(market=market, start=start, end=end)
    console.print(
        f"[green]OHLCV[/green] 성공={ohlcv_result['success']} "
        f"실패={ohlcv_result['failed']} 스킵={ohlcv_result['skipped']}"
    )

    fund_result = fetch_all_fundamentals(market=market)
    console.print(
        f"[green]재무[/green] 성공={fund_result['success']} "
        f"실패={fund_result['failed']}"
    )
    console.print("[bold cyan]== 파이프라인 완료 ==[/bold cyan]")
