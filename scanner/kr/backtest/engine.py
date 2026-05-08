"""백테스트 엔진 — 과거 스캔 결과를 재생해 패턴 성과를 측정한다."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from loguru import logger


def run_backtest(
    pattern_name: str,
    period_days: int = 90,
    hold_days: int = 10,
    min_score: float = 70.0,
) -> dict[str, Any]:
    """패턴 백테스트를 실행하고 요약 통계를 반환한다.

    Args:
        pattern_name: 백테스트할 패턴명.
        period_days:  과거 몇 일치 스캔 결과를 사용할지.
        hold_days:    신호 후 최대 보유 일수.
        min_score:    신뢰도 점수 최소값.

    Returns:
        백테스트 요약 딕셔너리.
    """
    import pandas as pd
    from sqlalchemy import select

    from scanner.db.models import OHLCVDaily, ScanResult
    from scanner.db.session import get_session

    period_end = date.today()
    period_start = period_end - timedelta(days=period_days)

    logger.info(
        "백테스트 시작 | pattern={} period={}~{} hold_days={} min_score={}",
        pattern_name, period_start, period_end, hold_days, min_score,
    )

    with get_session() as session:
        signals = session.execute(
            select(ScanResult).where(
                ScanResult.pattern_name == pattern_name,
                ScanResult.scan_date >= period_start,
                ScanResult.scan_date <= period_end,
                ScanResult.confidence_score >= min_score,
                ScanResult.entry_price.is_not(None),
                ScanResult.stop_loss.is_not(None),
                ScanResult.target_price.is_not(None),
            ).order_by(ScanResult.scan_date)
        ).scalars().all()

        if not signals:
            logger.warning("백테스트 대상 신호 없음")
            return _empty_result(pattern_name, period_start, period_end, period_days, hold_days, min_score)

        tickers = list({s.ticker for s in signals})
        ohlcv_rows = session.execute(
            select(OHLCVDaily).where(
                OHLCVDaily.ticker.in_(tickers),
                OHLCVDaily.date >= period_start,
                OHLCVDaily.date <= period_end + timedelta(days=hold_days + 10),
            ).order_by(OHLCVDaily.ticker, OHLCVDaily.date)
        ).scalars().all()

    price_map: dict[str, list[tuple[date, float, float, float]]] = {}
    for row in ohlcv_rows:
        price_map.setdefault(row.ticker, []).append(
            (row.date, row.open, row.high, row.low)
        )

    trades: list[dict[str, Any]] = []
    for sig in signals:
        trade = _simulate_trade(sig, price_map.get(sig.ticker, []), hold_days)
        if trade is not None:
            trades.append(trade)

    if not trades:
        return _empty_result(pattern_name, period_start, period_end, period_days, hold_days, min_score)

    returns = [t["return_pct"] for t in trades]
    wins    = [t for t in trades if t["outcome"] == "win"]
    losses  = [t for t in trades if t["outcome"] == "loss"]
    timeout = [t for t in trades if t["outcome"] == "timeout"]

    total       = len(trades)
    win_count   = len(wins)
    loss_count  = len(losses)
    win_rate    = win_count / total if total else 0.0

    avg_return   = sum(returns) / total if total else 0.0
    avg_win_ret  = sum(t["return_pct"] for t in wins)  / len(wins)  if wins  else 0.0
    avg_loss_ret = sum(t["return_pct"] for t in losses) / len(losses) if losses else 0.0

    gross_profit = sum(t["return_pct"] for t in wins  if t["return_pct"] > 0) or 0.0
    gross_loss   = abs(sum(t["return_pct"] for t in losses if t["return_pct"] < 0)) or 1e-9
    profit_factor = gross_profit / gross_loss

    max_drawdown = _calc_max_drawdown([t["return_pct"] for t in trades])

    daily_counts: dict[str, int] = {}
    for t in trades:
        d = str(t["entry_date"])
        daily_counts[d] = daily_counts.get(d, 0) + 1

    result = {
        "pattern_name":   pattern_name,
        "period_start":   period_start.isoformat(),
        "period_end":     period_end.isoformat(),
        "period_days":    period_days,
        "hold_days":      hold_days,
        "min_score":      min_score,
        "total_signals":  total,
        "win_count":      win_count,
        "loss_count":     loss_count,
        "timeout_count":  len(timeout),
        "win_rate":       round(win_rate, 4),
        "avg_return_pct": round(avg_return, 4),
        "avg_win_pct":    round(avg_win_ret, 4),
        "avg_loss_pct":   round(avg_loss_ret, 4),
        "profit_factor":  round(profit_factor, 4),
        "max_drawdown":   round(max_drawdown, 4),
        "trades":         trades[:200],
        "daily_counts":   daily_counts,
    }

    logger.info(
        "백테스트 완료 | total={} win_rate={:.1%} avg_return={:.2f}%",
        total, win_rate, avg_return,
    )
    return result


def _simulate_trade(
    sig: Any,
    price_series: list[tuple[date, float, float, float]],
    hold_days: int,
) -> dict[str, Any] | None:
    """단일 신호의 가상 매매를 시뮬레이션한다.

    진입: sig.scan_date 다음 거래일 시가.
    청산: 목표가 도달(win) / 손절가 도달(loss) / hold_days 경과 후 종가(timeout).
    """
    entry_date = sig.scan_date
    entry_price = sig.entry_price
    stop_loss   = sig.stop_loss
    target      = sig.target_price

    future_bars = [b for b in price_series if b[0] > entry_date]
    if not future_bars:
        return None

    actual_entry = future_bars[0][1]  # 다음날 시가
    if actual_entry <= 0:
        return None

    outcome     = "timeout"
    exit_price  = None
    exit_date   = None

    for i, (bar_date, bar_open, bar_high, bar_low) in enumerate(future_bars[:hold_days]):
        if bar_high >= target:
            outcome    = "win"
            exit_price = target
            exit_date  = bar_date
            break
        if bar_low <= stop_loss:
            outcome    = "loss"
            exit_price = stop_loss
            exit_date  = bar_date
            break
    else:
        exit_date  = future_bars[min(hold_days - 1, len(future_bars) - 1)][0]
        exit_price = future_bars[min(hold_days - 1, len(future_bars) - 1)][1]

    return_pct = (exit_price - actual_entry) / actual_entry * 100 if actual_entry else 0.0

    return {
        "ticker":       sig.ticker,
        "entry_date":   entry_date.isoformat(),
        "exit_date":    exit_date.isoformat() if exit_date else None,
        "entry_price":  round(actual_entry, 4),
        "exit_price":   round(exit_price, 4),
        "return_pct":   round(return_pct, 4),
        "outcome":      outcome,
        "score":        round(sig.confidence_score, 2),
    }


def _calc_max_drawdown(returns: list[float]) -> float:
    """누적 수익률 기준 최대 낙폭(MDD)을 계산한다."""
    if not returns:
        return 0.0
    equity = 100.0
    peak   = equity
    mdd    = 0.0
    for r in returns:
        equity += r
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100
        if dd > mdd:
            mdd = dd
    return mdd


def _empty_result(
    pattern_name: str,
    period_start: date,
    period_end: date,
    period_days: int,
    hold_days: int,
    min_score: float,
) -> dict[str, Any]:
    """신호가 없을 때 반환할 빈 결과 딕셔너리."""
    return {
        "pattern_name":   pattern_name,
        "period_start":   period_start.isoformat(),
        "period_end":     period_end.isoformat(),
        "period_days":    period_days,
        "hold_days":      hold_days,
        "min_score":      min_score,
        "total_signals":  0,
        "win_count":      0,
        "loss_count":     0,
        "timeout_count":  0,
        "win_rate":       0.0,
        "avg_return_pct": 0.0,
        "avg_win_pct":    0.0,
        "avg_loss_pct":   0.0,
        "profit_factor":  0.0,
        "max_drawdown":   0.0,
        "trades":         [],
        "daily_counts":   {},
    }
