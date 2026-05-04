"""HTML 리포트 생성기.

``generate_daily_report(scan_date)`` 를 호출하면
``data/reports/YYYY-MM-DD/`` 디렉터리에 정적 HTML 파일을 생성한다.

출력 구조:
    data/reports/YYYY-MM-DD/
        index.html            ← 일일 요약 리포트
        double_bottom.html    ┐
        golden_cross.html     │ 패턴별 종목 목록
        box_breakout.html     │
        pullback.html         ┘
        stocks/
            {TICKER}.html     ← 종목별 상세 (차트 + AI 코멘트)
"""
from __future__ import annotations

import json
import math
import time
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from scanner.config import settings
from scanner.db.models import OHLCVDaily, ScanResult, Universe
from scanner.db.repository import get_scan_results
from scanner.db.session import get_session
from scanner.indicators.moving_average import sma
from scanner.indicators.rsi import rsi as compute_rsi
from scanner.reports.comment_generator import generate_comment

_TEMPLATE_DIR = Path(__file__).parent / "templates"

PATTERN_LABELS: dict[str, str] = {
    "double_bottom": "쌍바닥",
    "golden_cross":  "골든크로스",
    "box_breakout":  "박스 돌파",
    "pullback":      "눌림목",
}

_PATTERN_KEYS = list(PATTERN_LABELS.keys())


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------


def generate_daily_report(scan_date: date | None = None) -> Path:
    """지정 날짜의 스캔 결과로 HTML 리포트를 생성한다.

    Args:
        scan_date: 스캔 날짜. ``None`` 이면 오늘 날짜를 사용한다.

    Returns:
        생성된 ``index.html`` 의 절대 경로.
    """
    if scan_date is None:
        scan_date = date.today()

    t_start = time.perf_counter()
    logger.info("HTML 리포트 생성 시작: {}", scan_date)

    report_dir = settings.REPORTS_DIR / scan_date.isoformat()
    stocks_dir = report_dir / "stocks"
    stocks_dir.mkdir(parents=True, exist_ok=True)

    env = _build_jinja_env()

    with get_session() as session:
        rows_orm = get_scan_results(
            scan_date, session, min_score=settings_threshold(), passed_filters_only=False
        )
        rows = _attach_market(rows_orm, session)
        name_map = _load_ticker_names(session)

        # 패턴별 분류
        pattern_rows: dict[str, list[dict]] = {k: [] for k in _PATTERN_KEYS}
        for row in rows:
            pname = row["pattern_name"]
            if pname in pattern_rows:
                pattern_rows[pname].append(row)

        # 분포 집계
        market_dist: dict[str, int] = {}
        for row in rows:
            mkt = (row.get("market") or "KR").upper()
            market_dist[mkt] = market_dist.get(mkt, 0) + 1

        pattern_dist = {k: len(v) for k, v in pattern_rows.items()}
        top_results = sorted(rows, key=lambda r: r["confidence_score"], reverse=True)[:20]

        total_active = _count_active_tickers(session)

        # ── 종목 상세 페이지 ────────────────────────────────────────
        for row in rows:
            ticker = row["ticker"]
            df_ohlcv = _load_ohlcv(ticker, session)
            ohlcv_json = _build_ohlcv_json(df_ohlcv)

            html = env.get_template("stock_detail.html").render(
                scan_date=scan_date.isoformat(),
                ticker=ticker,
                name=name_map.get(ticker, ""),
                pattern_name=row["pattern_name"],
                pattern_labels=PATTERN_LABELS,
                market=row.get("market", "KR"),
                confidence_score=row["confidence_score"],
                entry_price=row.get("entry_price"),
                stop_loss=row.get("stop_loss"),
                target_price=row.get("target_price"),
                risk_reward_ratio=row.get("risk_reward_ratio"),
                trend_weekly=row.get("trend_weekly"),
                ohlcv_json=ohlcv_json,
                ai_comment_phases=generate_comment(row),
            )
            (stocks_dir / f"{ticker}.html").write_text(html, encoding="utf-8")

        # ── 패턴별 목록 페이지 ──────────────────────────────────────
        for pkey, prows in pattern_rows.items():
            html = env.get_template("pattern_list.html").render(
                scan_date=scan_date.isoformat(),
                pattern_key=pkey,
                pattern_label=PATTERN_LABELS[pkey],
                pattern_labels=PATTERN_LABELS,
                rows=prows,
            )
            (report_dir / f"{pkey}.html").write_text(html, encoding="utf-8")

        # ── 인덱스 페이지 ───────────────────────────────────────────
        duration = time.perf_counter() - t_start
        html = env.get_template("daily_report.html").render(
            scan_date=scan_date.isoformat(),
            total_tickers=total_active,
            duration_seconds=duration,
            pattern_dist=pattern_dist,
            market_dist=market_dist,
            top_results=top_results,
            pattern_labels=PATTERN_LABELS,
        )
        index_path = report_dir / "index.html"
        index_path.write_text(html, encoding="utf-8")

    logger.info("HTML 리포트 완료 ({:.1f}초): {}", time.perf_counter() - t_start, index_path)
    return index_path


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------


def settings_threshold() -> float:
    """config 의 CONFIDENCE_THRESHOLD 를 지연 임포트로 읽는다."""
    from scanner.config import CONFIDENCE_THRESHOLD
    return CONFIDENCE_THRESHOLD


def _build_jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )


def _attach_market(
    rows: list[ScanResult], session: Session
) -> list[dict[str, Any]]:
    """ScanResult ORM 목록을 dict 로 변환하고 market 필드를 주입한다."""
    tickers = list({r.ticker for r in rows})
    if not tickers:
        return []

    stmt = select(Universe.ticker, Universe.market).where(Universe.ticker.in_(tickers))
    market_map: dict[str, str] = {
        row[0]: row[1] for row in session.execute(stmt).all()
    }

    return [
        {
            "ticker":           r.ticker,
            "pattern_name":     r.pattern_name,
            "confidence_score": r.confidence_score,
            "entry_price":      r.entry_price,
            "stop_loss":        r.stop_loss,
            "target_price":     r.target_price,
            "risk_reward_ratio":r.risk_reward_ratio,
            "trend_weekly":     r.trend_weekly,
            "passed_filters":   r.passed_filters,
            "pattern_details":  r.pattern_details or {},
            "market":           market_map.get(r.ticker, "KR"),
        }
        for r in rows
    ]


def _load_ticker_names(session: Session) -> dict[str, str]:
    """ticker → name 매핑을 반환한다."""
    stmt = select(Universe.ticker, Universe.name)
    return {row[0]: row[1] for row in session.execute(stmt).all()}


def _count_active_tickers(session: Session) -> int:
    stmt = select(Universe.ticker).where(Universe.is_active.is_(True))
    return len(list(session.execute(stmt).scalars().all()))


def _load_ohlcv(ticker: str, session: Session, lookback: int = 120) -> pd.DataFrame:
    """일봉 OHLCV 최근 N행을 날짜 오름차순으로 반환한다."""
    stmt = (
        select(OHLCVDaily)
        .where(OHLCVDaily.ticker == ticker)
        .order_by(OHLCVDaily.date.desc())
        .limit(lookback)
    )
    rows = list(session.execute(stmt).scalars().all())
    if not rows:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    rows.sort(key=lambda r: r.date)
    return pd.DataFrame([
        {
            "date":   r.date.isoformat(),
            "open":   r.open,
            "high":   r.high,
            "low":    r.low,
            "close":  r.close,
            "volume": r.volume,
        }
        for r in rows
    ])


def _build_ohlcv_json(df: pd.DataFrame) -> str:
    """OHLCV DataFrame 을 TradingView Lightweight Charts 포맷 JSON 문자열로 변환한다."""
    if df.empty:
        empty: dict[str, list] = {
            "candles": [], "volume": [], "ma5": [], "ma20": [], "ma60": [], "rsi": [],
        }
        return json.dumps(empty)

    dates = df["date"].tolist()
    close = df["close"].reset_index(drop=True)

    ma5  = sma(close, 5)
    ma20 = sma(close, 20)
    ma60 = sma(close, 60)
    rsi_vals = compute_rsi(close, 14)

    def _to_tv(series: pd.Series) -> list[dict]:
        out = []
        for i, val in enumerate(series.tolist()):
            if val is None or (isinstance(val, float) and math.isnan(val)):
                continue
            out.append({"time": dates[i], "value": round(float(val), 4)})
        return out

    candles = [
        {
            "time":  row["date"],
            "open":  row["open"],
            "high":  row["high"],
            "low":   row["low"],
            "close": row["close"],
        }
        for _, row in df.iterrows()
    ]

    volume = [
        {
            "time":  row["date"],
            "value": row["volume"],
            "color": "#3fb950" if row["close"] >= row["open"] else "#f85149",
        }
        for _, row in df.iterrows()
    ]

    return json.dumps(
        {
            "candles": candles,
            "volume":  volume,
            "ma5":     _to_tv(ma5),
            "ma20":    _to_tv(ma20),
            "ma60":    _to_tv(ma60),
            "rsi":     _to_tv(rsi_vals),
        },
        ensure_ascii=False,
    )


__all__ = ["generate_daily_report", "PATTERN_LABELS"]
