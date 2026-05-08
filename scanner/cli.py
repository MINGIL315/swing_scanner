"""Scanner CLI 진입점."""
from __future__ import annotations

from typing import Optional

import typer
from loguru import logger
from rich.console import Console

app = typer.Typer(
    name="scanner",
    help="스윙매매 차트 발굴 시스템",
    no_args_is_help=True,
)
console = Console()


@app.command()
def version() -> None:
    """현재 버전을 출력한다."""
    from scanner import __version__

    typer.echo(f"swing-scanner {__version__}")


@app.command("update-universe")
def update_universe(
    market: str = typer.Option(
        "all",
        "--market",
        "-m",
        help="갱신할 시장: kr | us | all",
    ),
) -> None:
    """종목 유니버스를 최신 구성종목으로 갱신한다.

    kr  → KOSPI200 (pykrx)\n
    us  → S&P500   (Wikipedia)\n
    all → 둘 다
    """
    from scanner.config import setup_logger
    from scanner.kr.universe import update_kospi200
    from scanner.us.universe import update_sp500
    from scanner.db.migrations import init_database

    setup_logger()
    init_database()

    m = market.upper()
    if m in ("KR", "ALL"):
        count = update_kospi200()
        console.print(f"[green]KOSPI200[/green] {count} 종목 갱신 완료")
    if m in ("US", "ALL"):
        count = update_sp500()
        console.print(f"[green]S&P500[/green] {count} 종목 갱신 완료")
    if m not in ("KR", "US", "ALL"):
        console.print(f"[red]알 수 없는 시장: {market} (kr / us / all 중 선택)[/red]")
        raise typer.Exit(code=1)


@app.command("fetch")
def fetch(
    ticker: str = typer.Argument(..., help="종목 코드 (예: 005930, AAPL)"),
    days: int = typer.Option(365, "--days", "-d", help="과거 몇 일치 데이터 수집"),
) -> None:
    """단일 종목의 OHLCV + 재무 데이터를 수집한다."""
    from datetime import date, timedelta

    from scanner.config import setup_logger
    from scanner.data_pipeline import (
        _fetch_fundamental_one,
        _fetch_ohlcv_one,
        _get_market,
    )
    from scanner.db.migrations import init_database

    setup_logger()
    init_database()

    today = date.today()
    start = today - timedelta(days=days)
    market = _get_market(ticker)

    console.print(f"[cyan]{ticker}[/cyan] ({market}) OHLCV 수집 중...")
    _, ok_o, err_o = _fetch_ohlcv_one(ticker, market, start, today)
    if ok_o:
        console.print(f"[green]OHLCV 완료[/green]")
    else:
        console.print(f"[red]OHLCV 실패: {err_o}[/red]")

    console.print(f"[cyan]{ticker}[/cyan] 재무 수집 중...")
    _, ok_f, err_f = _fetch_fundamental_one(ticker, market, today)
    if ok_f:
        console.print(f"[green]재무 완료[/green]")
    else:
        console.print(f"[red]재무 실패: {err_f}[/red]")


@app.command("fetch-all")
def fetch_all(
    market: str = typer.Option(
        "all",
        "--market",
        "-m",
        help="수집할 시장: kr | us | all",
    ),
    days: int = typer.Option(365, "--days", "-d", help="과거 몇 일치 데이터 수집"),
) -> None:
    """모든 활성 종목의 OHLCV + 재무 데이터를 일괄 수집한다."""
    from datetime import date, timedelta

    from scanner.config import setup_logger
    from scanner.data_pipeline import run_data_pipeline
    from scanner.db.migrations import init_database

    setup_logger()
    init_database()

    today = date.today()
    start = today - timedelta(days=days)
    run_data_pipeline(market=market.upper(), start=start, end=today)


@app.command("test-pattern")
def test_pattern(
    ticker: str = typer.Argument(..., help="종목 코드 (예: 005930, AAPL)"),
    pattern: Optional[str] = typer.Option(
        None,
        "--pattern",
        "-p",
        help="패턴 이름: double_bottom | golden_cross | box_breakout | pullback (기본: 전체)",
    ),
    days: int = typer.Option(500, "--days", "-d", help="최근 N일 데이터 로드"),
) -> None:
    """특정 종목에 패턴 탐지기를 실행해 디버그 결과를 출력한다."""
    from datetime import date, timedelta

    from rich.table import Table

    from scanner.config import setup_logger
    from scanner.data_pipeline import _fetch_ohlcv_one, _get_market
    from scanner.db.migrations import init_database
    from scanner.db.session import get_session
    from scanner.db.models import OHLCVDaily
    from scanner.kr.patterns import ALL_DETECTORS, get_detector

    setup_logger()
    init_database()

    # ── 데이터 로드 ────────────────────────────────────────────────
    # DB 에서 먼저 시도, 없으면 직접 수집
    import pandas as pd
    from sqlalchemy import select

    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    with get_session() as session:
        rows = session.execute(
            select(OHLCVDaily)
            .where(OHLCVDaily.ticker == ticker)
            .where(OHLCVDaily.date >= start_date)
            .order_by(OHLCVDaily.date)
        ).scalars().all()

    if rows:
        df = pd.DataFrame([
            {
                "date": r.date,
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
            }
            for r in rows
        ])
        console.print(f"[dim]DB에서 {len(df)}행 로드[/dim]")
    else:
        console.print(f"[yellow]DB 데이터 없음. {ticker} 직접 수집 중...[/yellow]")
        market = _get_market(ticker)
        result_tuple = _fetch_ohlcv_one(ticker, market, start_date, end_date)
        if not result_tuple[1]:
            console.print(f"[red]데이터 수집 실패: {result_tuple[2]}[/red]")
            raise typer.Exit(code=1)
        # 수집 후 DB 재조회
        with get_session() as session:
            rows = session.execute(
                select(OHLCVDaily)
                .where(OHLCVDaily.ticker == ticker)
                .where(OHLCVDaily.date >= start_date)
                .order_by(OHLCVDaily.date)
            ).scalars().all()
        df = pd.DataFrame([
            {"date": r.date, "open": r.open, "high": r.high,
             "low": r.low, "close": r.close, "volume": r.volume}
            for r in rows
        ])
        console.print(f"[dim]수집 후 {len(df)}행 로드[/dim]")

    if df.empty:
        console.print("[red]데이터가 없습니다.[/red]")
        raise typer.Exit(code=1)

    # ── 탐지기 선택 ────────────────────────────────────────────────
    if pattern:
        detector = get_detector(pattern)
        if detector is None:
            valid = ", ".join(d.name for d in ALL_DETECTORS)
            console.print(f"[red]알 수 없는 패턴: {pattern}. 가능한 값: {valid}[/red]")
            raise typer.Exit(code=1)
        detectors = [detector]
    else:
        detectors = ALL_DETECTORS

    # ── 패턴 탐지 실행 ─────────────────────────────────────────────
    found_any = False
    for det in detectors:
        console.rule(f"[bold]{det.display_name}[/bold] ({det.name})")
        result = det.detect(df, ticker)
        if result is None:
            console.print("[yellow]  → 탐지되지 않음[/yellow]")
            continue

        found_any = True
        sig = det.entry_signal(df)

        tbl = Table(show_header=False, padding=(0, 1))
        tbl.add_column("항목", style="cyan")
        tbl.add_column("값")

        tbl.add_row("탐지일", str(result.detected_at))
        tbl.add_row("진입가", f"{result.entry_price:,.4f}")
        tbl.add_row("손절가", f"{result.stop_loss:,.4f}")
        tbl.add_row("목표가", f"{result.target_price:,.4f}")
        tbl.add_row("손익비", str(result.risk_reward_ratio))
        tbl.add_row("패턴 점수", f"{result.raw_score:.1f} / 100")
        tbl.add_row("진입 강도", f"{sig.strength:.0f} / 100")
        for sig_name, sig_val in sig.signals.items():
            mark = "[green]✓[/green]" if sig_val else "[red]✗[/red]"
            tbl.add_row(f"  {sig_name}", mark)
        for k, v in result.details.items():
            tbl.add_row(f"  {k}", str(v))

        console.print(tbl)

    if not found_any:
        console.print("\n[bold yellow]탐지된 패턴 없음[/bold yellow]")


# ---------------------------------------------------------------------------
# 패턴 표시 상수 (색상 + 한국어 이름)
# ---------------------------------------------------------------------------

PATTERN_STYLES: dict[str, tuple[str, str]] = {
    "double_bottom": ("쌍바닥", "cyan"),
    "golden_cross": ("골든크로스", "yellow"),
    "box_breakout": ("박스 돌파", "magenta"),
    "pullback": ("눌림목", "green"),
}


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------

def _parse_date(date_str: str | None) -> "date":
    """날짜 문자열을 date 객체로 변환한다.

    Args:
        date_str: "YYYY-MM-DD" 또는 "today" 또는 None (→ 오늘).

    Returns:
        date 객체.
    """
    from datetime import date as _date

    if date_str is None or date_str.lower() == "today":
        return _date.today()
    try:
        return _date.fromisoformat(date_str)
    except ValueError:
        console.print(f"[red]날짜 형식 오류: {date_str}  (YYYY-MM-DD 또는 today 사용)[/red]")
        raise typer.Exit(code=1)


def _pattern_markup(pattern_name: str) -> str:
    """패턴명을 색상 markup 문자열로 변환한다."""
    display, color = PATTERN_STYLES.get(pattern_name, (pattern_name, "white"))
    return f"[{color}]{display}[/{color}]"


def _print_results_table(rows: list, title: str, top_n: int = 20) -> None:
    """ScanResult ORM 목록을 Rich 테이블로 출력한다.

    Args:
        rows  : ScanResult ORM 인스턴스 목록 (confidence_score 내림차순 가정).
        title : 테이블 제목.
        top_n : 출력할 최대 행 수.
    """
    from rich.table import Table

    tbl = Table(title=title, show_lines=False, header_style="bold")
    tbl.add_column("#", style="dim", width=4, justify="right")
    tbl.add_column("종목", min_width=10)
    tbl.add_column("패턴", min_width=12)
    tbl.add_column("점수", justify="right", min_width=6)
    tbl.add_column("진입가", justify="right", min_width=10)
    tbl.add_column("손절가", justify="right", min_width=10)
    tbl.add_column("목표가", justify="right", min_width=10)
    tbl.add_column("R:R", justify="right", min_width=5)
    tbl.add_column("주봉", min_width=8)
    tbl.add_column("필터", justify="center", min_width=4)

    for i, row in enumerate(rows[:top_n], 1):
        pname = row.pattern_name
        display, color = PATTERN_STYLES.get(pname, (pname, "white"))
        score = row.confidence_score
        if score >= 80:
            score_str = f"[bold green]{score:.1f}[/bold green]"
        elif score >= 70:
            score_str = f"[bold yellow]{score:.1f}[/bold yellow]"
        else:
            score_str = f"{score:.1f}"

        tbl.add_row(
            str(i),
            row.ticker,
            f"[{color}]{display}[/{color}]",
            score_str,
            f"{row.entry_price:,.2f}" if row.entry_price else "-",
            f"{row.stop_loss:,.2f}" if row.stop_loss else "-",
            f"{row.target_price:,.2f}" if row.target_price else "-",
            f"1:{row.risk_reward_ratio:.1f}" if row.risk_reward_ratio else "-",
            row.trend_weekly or "-",
            "[green]✓[/green]" if row.passed_filters else "[red]✗[/red]",
        )

    console.print(tbl)


# ---------------------------------------------------------------------------
# scan 명령어
# ---------------------------------------------------------------------------

@app.command("scan")
def scan(
    market: str = typer.Option(
        "all", "--market", "-m", help="스캔 시장: kr | us | all",
    ),
    pattern: Optional[str] = typer.Option(
        None, "--pattern", "-p",
        help="패턴 필터 (쉼표 구분, 예: pullback,box_breakout)",
    ),
    min_confidence: float = typer.Option(
        70.0, "--min-confidence", help="최소 신뢰도 점수 (0~100)",
    ),
    no_volume_filter: bool = typer.Option(
        False, "--no-volume-filter", help="거래량 필터 비활성화",
    ),
    with_fundamental_filter: bool = typer.Option(
        False, "--with-fundamental-filter", help="재무 필터 활성화",
    ),
    skip_fetch: bool = typer.Option(
        False, "--skip-fetch", help="데이터 fetch 생략 (DB 기존 데이터로 스캔)",
    ),
    no_report: bool = typer.Option(
        False, "--no-report", help="스캔 완료 후 HTML 리포트 생성 생략",
    ),
) -> None:
    """전체 파이프라인을 실행한다.

    fetch → scan_universe → DB 저장 → 결과 요약 출력.
    """
    import concurrent.futures as cf
    import time
    from datetime import date, timedelta

    from rich.panel import Panel
    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
        TimeRemainingColumn,
    )
    from rich.table import Table

    from scanner.config import FETCH_MAX_WORKERS, setup_logger
    from scanner.db.universe_db import get_active_tickers
    from scanner.db.migrations import init_database
    from scanner.db.repository import get_scan_results, save_scan_results
    from scanner.db.session import get_session
    from scanner.pipeline import (
        _load_daily_dfs,
        _load_fundamentals,
        _load_market_map,
        _maybe_update_universe,
    )
    from scanner.kr.scanner import analyze_ticker

    setup_logger()
    init_database()

    patterns = [p.strip() for p in pattern.split(",")] if pattern else None
    market_upper = market.upper()

    console.print(Panel(
        f"시장: [bold]{market_upper}[/bold]  |  "
        f"최소 신뢰도: [bold]{min_confidence}[/bold]  |  "
        f"fetch 건너뜀: [bold]{skip_fetch}[/bold]",
        title="[bold cyan]Swing Scanner — 스캔 시작[/bold cyan]",
        border_style="cyan",
    ))
    logger.info("scan 명령어 시작 | market={} skip_fetch={} min_confidence={}", market_upper, skip_fetch, min_confidence)

    t_start = time.monotonic()

    # ── Phase 1: 유니버스 확인 + 데이터 fetch ─────────────────────────
    logger.info("Phase 1 진입: 유니버스 확인 + 데이터 fetch")
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as progress:
            task1 = progress.add_task("[bold]유니버스 확인 중...[/bold]", total=None)
            _maybe_update_universe(market_upper)
            progress.update(task1, description="[green]✓ 유니버스 확인[/green]")

            if not skip_fetch:
                progress.update(task1, description="[bold]데이터 fetch 중...[/bold]")
                from scanner.data_pipeline import run_data_pipeline
                end_date = date.today()
                start_date = end_date - timedelta(days=365)
                run_data_pipeline(market=market_upper, start=start_date, end=end_date)
                progress.update(task1, description="[green]✓ 데이터 fetch 완료[/green]")
    except KeyboardInterrupt:
        console.print("\n[yellow]fetch 단계에서 중단. 저장할 결과가 없습니다.[/yellow]")
        logger.warning("사용자 중단 — fetch 단계")
        raise typer.Exit(code=0)

    console.print("[dim]✓ Phase 1: 유니버스 + 데이터 fetch[/dim]")
    logger.info("Phase 1 완료")

    # ── Phase 2: 데이터 로드 ─────────────────────────────────────────
    logger.info("Phase 2 진입: 일봉 데이터 로드")
    tickers = get_active_tickers(market_upper)
    if not tickers:
        console.print("[yellow]활성 종목이 없습니다. 유니버스 갱신 필요.[/yellow]")
        logger.warning("활성 종목 없음 — 조기 종료")
        raise typer.Exit(code=0)

    daily_dfs = _load_daily_dfs(tickers)
    market_map = _load_market_map(tickers)
    fundamentals_map = _load_fundamentals(tickers) if with_fundamental_filter else None
    logger.info("데이터 로드 완료: {}개 종목", len(daily_dfs))

    # ── Phase 3: 패턴 탐지 (Ctrl+C 시 완료분 부분 저장) ─────────────
    logger.info("Phase 3 진입: 패턴 탐지 ({}종목, workers={})", len(daily_dfs), FETCH_MAX_WORKERS)
    results: list = []
    interrupted = False

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=True,
    ) as progress:
        task2 = progress.add_task(
            "[bold]패턴 탐지 중...[/bold]",
            total=len(daily_dfs),
        )
        try:
            with cf.ThreadPoolExecutor(max_workers=FETCH_MAX_WORKERS) as executor:
                future_map = {
                    executor.submit(
                        analyze_ticker,
                        t,
                        market_map.get(t, "US"),
                        daily_dfs[t],
                        fundamentals_map.get(t) if fundamentals_map else None,
                    ): t
                    for t in daily_dfs
                }
                for future in cf.as_completed(future_map):
                    t = future_map[future]
                    try:
                        results.append(future.result())
                    except Exception as exc:
                        logger.error("{} 처리 실패: {}", t, exc)
                    finally:
                        progress.advance(task2)
        except KeyboardInterrupt:
            interrupted = True
            console.print(
                f"\n[yellow]Ctrl+C 감지 — 완료된 {len(results)}건 저장 후 종료[/yellow]"
            )
            logger.warning("사용자 중단: {}개 종목 완료, 부분 저장 시작", len(results))

    phase_label = f"(부분: {len(results)}/{len(daily_dfs)})" if interrupted else f"({len(daily_dfs)}종목)"
    console.print(f"[dim]✓ Phase 3: 패턴 탐지 {phase_label}[/dim]")
    logger.info("Phase 3 완료: {}개 결과", len(results))

    # ── 후처리 ───────────────────────────────────────────────────────
    if no_volume_filter:
        for r in results:
            r.passed_volume = True

    if patterns:
        for r in results:
            pairs = [
                (pr, sc)
                for pr, sc in zip(r.pattern_results, r.confidence_scores)
                if pr.pattern_name in patterns
            ]
            if pairs:
                r.pattern_results, r.confidence_scores = map(list, zip(*pairs))
            else:
                r.pattern_results = []
                r.confidence_scores = []

    # ── Phase 4: DB 저장 ─────────────────────────────────────────────
    logger.info("Phase 4 진입: DB 저장")
    try:
        with get_session() as session:
            saved_count = save_scan_results(results, session)
    except Exception as exc:
        logger.error("DB 저장 실패: {}", exc)
        console.print(f"[red]DB 저장 실패: {exc}[/red]")
        raise typer.Exit(code=1)

    console.print(f"[dim]✓ Phase 4: DB 저장 ({saved_count}건)[/dim]")
    logger.info("Phase 4 완료: {}건 저장", saved_count)

    # ── 상위 결과 조회 ────────────────────────────────────────────────
    scan_date = date.today()
    min_score_arg = min_confidence if min_confidence > 0 else None
    with get_session() as session:
        top_results = get_scan_results(
            scan_date=scan_date,
            session=session,
            min_score=min_score_arg,
        )

    pattern_dist: dict[str, int] = {}
    for r in results:
        for pr in r.pattern_results:
            pattern_dist[pr.pattern_name] = pattern_dist.get(pr.pattern_name, 0) + 1

    duration = time.monotonic() - t_start
    total_patterns = sum(len(r.pattern_results) for r in results)
    logger.info("scan 완료 | 패턴={}건 저장={}건 소요={:.1f}초", total_patterns, saved_count, duration)

    # ── 요약 패널 ─────────────────────────────────────────────────────
    panel_title = "[bold yellow]⚠ 스캔 완료 (부분)[/bold yellow]" if interrupted else "[bold green]스캔 완료[/bold green]"
    panel_border = "yellow" if interrupted else "green"

    summary_grid = Table.grid(padding=(0, 2))
    summary_grid.add_column(style="bold cyan", min_width=16)
    summary_grid.add_column(justify="right", style="bold")
    summary_grid.add_row("스캔 기준일", str(scan_date))
    summary_grid.add_row("스캔 시장", market_upper)
    summary_grid.add_row("스캔 종목 수", f"{len(results)}/{len(daily_dfs)}" if interrupted else str(len(daily_dfs)))
    summary_grid.add_row("탐지 패턴 수", str(total_patterns))
    summary_grid.add_row("DB 저장 건수", str(saved_count))
    summary_grid.add_row("소요 시간", f"{duration:.1f}초")

    if pattern_dist:
        summary_grid.add_row("", "")
        for pname, cnt in sorted(pattern_dist.items(), key=lambda x: -x[1]):
            display, color = PATTERN_STYLES.get(pname, (pname, "white"))
            summary_grid.add_row(f"[{color}]{display}[/{color}]", str(cnt))

    console.print(Panel(summary_grid, title=panel_title, border_style=panel_border))

    if top_results:
        _print_results_table(top_results[:10], title="TOP 10 — 신뢰도 순위", top_n=10)

    # ── HTML 리포트 자동 생성 ─────────────────────────────────────────
    if not no_report and not interrupted:
        try:
            from scanner.kr.reports.html_report import generate_daily_report
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                TimeElapsedColumn(),
                console=console,
                transient=True,
            ) as progress:
                progress.add_task("[bold]HTML 리포트 생성 중...[/bold]", total=None)
                index_path = generate_daily_report(scan_date)
            console.print(f"[green]✓ HTML 리포트 생성 완료[/green] → {index_path}")
        except Exception as exc:
            logger.warning("HTML 리포트 생성 실패 (무시): {}", exc)
            console.print(f"[yellow]HTML 리포트 생성 실패 (무시): {exc}[/yellow]")

    if interrupted:
        raise typer.Exit(code=0)


# ---------------------------------------------------------------------------
# results 명령어
# ---------------------------------------------------------------------------

@app.command("results")
def results(
    date_str: Optional[str] = typer.Option(
        None, "--date", "-d",
        help="조회 날짜 (YYYY-MM-DD 또는 today, 기본: 오늘)",
    ),
    pattern: Optional[str] = typer.Option(
        None, "--pattern", "-p",
        help="패턴 필터: double_bottom | golden_cross | box_breakout | pullback",
    ),
    market: Optional[str] = typer.Option(
        None, "--market", "-m", help="시장 필터: kr | us",
    ),
    top: int = typer.Option(20, "--top", "-n", help="상위 N개 출력"),
    min_confidence: float = typer.Option(
        0.0, "--min-confidence", help="최소 신뢰도 점수",
    ),
    passed_only: bool = typer.Option(
        False, "--passed-only", help="거래량·재무 필터 통과 종목만 표시",
    ),
) -> None:
    """스캔 결과를 조회해 테이블로 출력한다.

    Args:
        date_str       : 조회 날짜 (기본: 오늘).
        pattern        : 패턴 이름 필터.
        market         : 시장 코드 필터.
        top            : 출력할 최대 행 수.
        min_confidence : 최소 신뢰도 점수.
        passed_only    : 필터 통과 종목만 출력.
    """
    from sqlalchemy import select

    from scanner.config import setup_logger
    from scanner.db.migrations import init_database
    from scanner.db.models import Universe
    from scanner.db.repository import get_scan_results
    from scanner.db.session import get_session

    setup_logger()
    init_database()

    target_date = _parse_date(date_str)

    market_tickers: list[str] | None = None
    if market:
        with get_session() as session:
            market_tickers = list(
                session.execute(
                    select(Universe.ticker)
                    .where(Universe.market == market.upper())
                    .where(Universe.is_active.is_(True))
                ).scalars().all()
            )
        if not market_tickers:
            console.print(
                f"[yellow]{market.upper()} 시장 종목이 없습니다. "
                f"'scanner update-universe --market {market.lower()}' 를 먼저 실행하세요.[/yellow]"
            )
            raise typer.Exit(code=0)

    with get_session() as session:
        rows = get_scan_results(
            scan_date=target_date,
            session=session,
            market_tickers=market_tickers,
            min_score=min_confidence if min_confidence > 0 else None,
            passed_filters_only=passed_only,
        )

    if pattern:
        rows = [r for r in rows if r.pattern_name == pattern]

    if not rows:
        console.print(
            f"[yellow]{target_date} 날짜에 조건에 맞는 스캔 결과가 없습니다.[/yellow]"
        )
        raise typer.Exit(code=0)

    _print_results_table(rows[:top], title=f"스캔 결과 — {target_date}", top_n=top)
    console.print(f"[dim]총 {len(rows)}건 중 {min(top, len(rows))}건 표시[/dim]")


# ---------------------------------------------------------------------------
# show 명령어
# ---------------------------------------------------------------------------

@app.command("show")
def show(
    ticker: str = typer.Argument(..., help="종목 코드 (예: 005930, AAPL)"),
    date_str: Optional[str] = typer.Option(
        None, "--date", "-d",
        help="조회 날짜 (YYYY-MM-DD 또는 today, 기본: 오늘)",
    ),
) -> None:
    """특정 종목의 스캔 결과 상세를 출력한다.

    Args:
        ticker  : 종목 코드.
        date_str: 조회 날짜 (기본: 오늘).
    """
    from rich.panel import Panel
    from rich.table import Table
    from sqlalchemy import select

    from scanner.config import setup_logger
    from scanner.db.migrations import init_database
    from scanner.db.models import ScanResult
    from scanner.db.session import get_session

    setup_logger()
    init_database()

    target_date = _parse_date(date_str)
    ticker_upper = ticker.upper()

    with get_session() as session:
        rows = session.execute(
            select(ScanResult)
            .where(ScanResult.scan_date == target_date)
            .where(ScanResult.ticker == ticker_upper)
            .order_by(ScanResult.confidence_score.desc())
        ).scalars().all()

    if not rows:
        console.print(
            f"[yellow]{ticker_upper} 종목의 {target_date} 스캔 결과가 없습니다.[/yellow]"
        )
        raise typer.Exit(code=0)

    for row in rows:
        display, color = PATTERN_STYLES.get(row.pattern_name, (row.pattern_name, "white"))

        tbl = Table(show_header=False, padding=(0, 2))
        tbl.add_column("항목", style="cyan", min_width=16)
        tbl.add_column("값")

        tbl.add_row("패턴", _pattern_markup(row.pattern_name))
        tbl.add_row("신뢰도 점수", f"[bold]{row.confidence_score:.1f}[/bold] / 100")
        tbl.add_row("진입가", f"{row.entry_price:,.2f}" if row.entry_price else "-")
        tbl.add_row("손절가", f"{row.stop_loss:,.2f}" if row.stop_loss else "-")
        tbl.add_row("목표가", f"{row.target_price:,.2f}" if row.target_price else "-")
        tbl.add_row(
            "손익비",
            f"1 : {row.risk_reward_ratio:.2f}" if row.risk_reward_ratio else "-",
        )
        tbl.add_row("주봉 추세", row.trend_weekly or "-")
        tbl.add_row(
            "필터 통과",
            "[green]✓ 통과[/green]" if row.passed_filters else "[red]✗ 미통과[/red]",
        )

        if row.pattern_details:
            tbl.add_row("", "")
            for k, v in row.pattern_details.items():
                tbl.add_row(f"  {k}", str(v))

        console.print(
            Panel(
                tbl,
                title=f"[bold {color}]{ticker_upper} — {display}[/bold {color}]",
                border_style=color,
            )
        )


# ---------------------------------------------------------------------------
# report 명령어
# ---------------------------------------------------------------------------

@app.command("report")
def report(
    date_str: Optional[str] = typer.Option(
        None, "--date", "-d",
        help="리포트 날짜 (YYYY-MM-DD 또는 today, 기본: 오늘)",
    ),
    open_browser: bool = typer.Option(
        False, "--open", "-o", help="생성 완료 후 브라우저로 열기",
    ),
) -> None:
    """HTML 리포트를 생성한다.

    data/reports/YYYY-MM-DD/index.html 이하에 정적 파일을 저장한다.
    """
    from scanner.config import setup_logger
    from scanner.db.migrations import init_database
    from scanner.kr.reports.html_report import generate_daily_report

    setup_logger()
    init_database()

    target_date = _parse_date(date_str)

    console.print(f"[cyan]{target_date}[/cyan] HTML 리포트 생성 중...")
    try:
        index_path = generate_daily_report(target_date)
    except Exception as exc:
        console.print(f"[red]리포트 생성 실패: {exc}[/red]")
        logger.exception("리포트 생성 실패")
        raise typer.Exit(code=1)

    console.print(f"[green]✓ 리포트 생성 완료[/green] → {index_path}")

    if open_browser:
        import webbrowser
        webbrowser.open(index_path.as_uri())


# ---------------------------------------------------------------------------
# export 명령어
# ---------------------------------------------------------------------------

@app.command("export")
def export(
    fmt: str = typer.Option(
        "csv", "--format", "-f",
        help="출력 형식: csv | xlsx",
    ),
    date_str: Optional[str] = typer.Option(
        None, "--date", "-d",
        help="내보낼 날짜 (YYYY-MM-DD 또는 today, 기본: 오늘)",
    ),
    min_confidence: float = typer.Option(
        0.0, "--min-confidence", help="최소 신뢰도 점수 (기본: 0 = 전체)",
    ),
) -> None:
    """스캔 결과를 CSV 또는 Excel 로 내보낸다.

    data/exports/YYYY-MM-DD.csv 또는 .xlsx 로 저장한다.
    """
    from scanner.config import setup_logger
    from scanner.db.migrations import init_database
    from scanner.kr.reports.excel_export import export_to_csv, export_to_excel

    setup_logger()
    init_database()

    target_date = _parse_date(date_str)
    fmt_lower = fmt.lower()

    if fmt_lower not in ("csv", "xlsx"):
        console.print(f"[red]알 수 없는 형식: {fmt}  (csv 또는 xlsx 사용)[/red]")
        raise typer.Exit(code=1)

    console.print(f"[cyan]{target_date}[/cyan] {fmt_lower.upper()} 내보내기 중...")
    try:
        if fmt_lower == "csv":
            out = export_to_csv(target_date, min_score=min_confidence)
        else:
            out = export_to_excel(target_date, min_score=min_confidence)
    except Exception as exc:
        console.print(f"[red]내보내기 실패: {exc}[/red]")
        logger.exception("내보내기 실패")
        raise typer.Exit(code=1)

    console.print(f"[green]✓ 내보내기 완료[/green] → {out}")


# ---------------------------------------------------------------------------
# backtest 명령어
# ---------------------------------------------------------------------------

@app.command("backtest")
def backtest(
    pattern: str = typer.Option(
        ..., "--pattern", "-p",
        help="패턴 이름: double_bottom | golden_cross | box_breakout | pullback",
    ),
    period: int = typer.Option(
        90, "--period", help="백테스트 기간 (일수, 30~730)",
    ),
    hold: int = typer.Option(
        10, "--hold", help="최대 보유 일수 (1~60)",
    ),
    min_score: float = typer.Option(
        70.0, "--min-score", help="최소 신뢰도 점수 (0~100)",
    ),
) -> None:
    """과거 스캔 결과로 패턴 백테스트를 실행한다.

    스캔 DB에 저장된 신호를 재생해 목표가/손절가 도달 여부를 시뮬레이션한다.
    """
    from rich.panel import Panel
    from rich.table import Table

    from scanner.kr.backtest.engine import run_backtest
    from scanner.config import setup_logger
    from scanner.db.migrations import init_database

    _VALID = {"double_bottom", "golden_cross", "box_breakout", "pullback"}
    if pattern not in _VALID:
        console.print(f"[red]알 수 없는 패턴: {pattern}  (가능: {', '.join(sorted(_VALID))})[/red]")
        raise typer.Exit(code=1)

    setup_logger()
    init_database()

    console.print(f"[cyan]{pattern}[/cyan] 백테스트 실행 중 (기간={period}일, 보유={hold}일, 최소점수={min_score})...")

    result = run_backtest(
        pattern_name=pattern,
        period_days=period,
        hold_days=hold,
        min_score=min_score,
    )

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="cyan", min_width=18)
    grid.add_column(justify="right", style="bold")

    grid.add_row("패턴",         result["pattern_name"])
    grid.add_row("기간",         f"{result['period_start']} ~ {result['period_end']}")
    grid.add_row("최대 보유일",  str(result["hold_days"]))
    grid.add_row("최소 점수",    str(result["min_score"]))
    grid.add_row("총 신호",      str(result["total_signals"]))
    grid.add_row("승리",         f"[green]{result['win_count']}[/green]")
    grid.add_row("손절",         f"[red]{result['loss_count']}[/red]")
    grid.add_row("타임아웃",     str(result["timeout_count"]))
    wr = result["win_rate"] * 100
    wr_color = "green" if wr >= 50 else "yellow" if wr >= 40 else "red"
    grid.add_row("승률",         f"[{wr_color}]{wr:.1f}%[/{wr_color}]")
    grid.add_row("평균 수익률",  f"{result['avg_return_pct']:+.2f}%")
    grid.add_row("평균 승리 수익", f"[green]{result['avg_win_pct']:+.2f}%[/green]")
    grid.add_row("평균 손절 손실", f"[red]{result['avg_loss_pct']:+.2f}%[/red]")
    grid.add_row("수익 팩터",    f"{result['profit_factor']:.2f}")
    grid.add_row("최대 낙폭",    f"[red]{result['max_drawdown']:.2f}%[/red]")

    console.print(Panel(grid, title=f"[bold]백테스트 결과 — {pattern}[/bold]", border_style="blue"))

    if result["trades"]:
        tbl = Table(title="최근 거래 내역 (최대 20건)", header_style="bold", show_lines=False)
        tbl.add_column("종목", style="mono")
        tbl.add_column("진입일")
        tbl.add_column("청산일")
        tbl.add_column("수익률", justify="right")
        tbl.add_column("결과", justify="center")

        for t in result["trades"][:20]:
            ret   = t["return_pct"]
            color = "green" if ret > 0 else "red" if ret < 0 else "white"
            outcome_icon = {"win": "[green]✓ 목표[/green]", "loss": "[red]✗ 손절[/red]", "timeout": "[yellow]⏱ 만료[/yellow]"}.get(t["outcome"], t["outcome"])
            tbl.add_row(
                t["ticker"],
                t["entry_date"],
                t["exit_date"] or "-",
                f"[{color}]{ret:+.2f}%[/{color}]",
                outcome_icon,
            )
        console.print(tbl)


# ---------------------------------------------------------------------------
# serve 명령어
# ---------------------------------------------------------------------------

@app.command("serve")
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="바인드 호스트"),
    port: int = typer.Option(8000, "--port", "-p", help="포트 번호"),
    reload: bool = typer.Option(False, "--reload", help="코드 변경 시 자동 재시작"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="브라우저 자동 열기"),
) -> None:
    """FastAPI 대시보드 서버를 시작한다.

    기본 주소: http://127.0.0.1:8000
    API 문서:  http://127.0.0.1:8000/docs
    """
    import threading
    import time
    import webbrowser

    from scanner.config import setup_logger
    from scanner.db.migrations import init_database

    setup_logger()
    init_database()

    url = f"http://{host}:{port}"
    console.print(f"[bold cyan]Swing Scanner 대시보드 시작[/bold cyan]")
    console.print(f"  서버:    {url}")
    console.print(f"  API 문서: {url}/docs")
    console.print(f"  종료:    Ctrl+C")

    if open_browser:
        def _open() -> None:
            time.sleep(1.5)
            webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()

    import uvicorn
    uvicorn.run(
        "scanner.api.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level="warning",
    )


if __name__ == "__main__":
    app()
