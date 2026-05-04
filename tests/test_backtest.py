"""백테스트 엔진 단위 테스트."""
from __future__ import annotations

import pytest

from scanner.backtest.engine import (
    _calc_max_drawdown,
    _empty_result,
    _simulate_trade,
    run_backtest,
)
from datetime import date


class _FakeSig:
    def __init__(self, ticker, scan_date, entry, stop, target, score=75.0):
        self.ticker = ticker
        self.scan_date = scan_date
        self.entry_price = entry
        self.stop_loss = stop
        self.target_price = target
        self.confidence_score = score


def _bars(base_date: date, prices: list[float]) -> list[tuple]:
    from datetime import timedelta
    result = []
    for i, p in enumerate(prices):
        d = base_date + timedelta(days=i + 1)
        result.append((d, p, p * 1.01, p * 0.99))
    return result


def test_calc_max_drawdown_empty():
    assert _calc_max_drawdown([]) == 0.0


def test_calc_max_drawdown_all_positive():
    mdd = _calc_max_drawdown([1.0, 2.0, 3.0])
    assert mdd == pytest.approx(0.0, abs=1e-6)


def test_calc_max_drawdown_drawdown():
    returns = [10.0, -20.0, 5.0]
    mdd = _calc_max_drawdown(returns)
    assert mdd > 0


def test_simulate_trade_win():
    sig = _FakeSig("AAPL", date(2025, 1, 1), entry=100, stop=95, target=110)
    bars = _bars(date(2025, 1, 1), [101, 105, 112])
    trade = _simulate_trade(sig, bars, hold_days=10)
    assert trade is not None
    assert trade["outcome"] == "win"
    assert trade["exit_price"] == pytest.approx(110.0)
    assert trade["return_pct"] > 0


def test_simulate_trade_loss():
    sig = _FakeSig("AAPL", date(2025, 1, 1), entry=100, stop=95, target=110)
    bars = []
    from datetime import timedelta
    d = date(2025, 1, 1)
    for i, (o, h, l) in enumerate([(100, 101, 94), (99, 100, 93)]):
        bars.append((d + timedelta(days=i + 1), o, h, l))

    trade = _simulate_trade(sig, bars, hold_days=10)
    assert trade is not None
    assert trade["outcome"] == "loss"
    assert trade["exit_price"] == pytest.approx(95.0)


def test_simulate_trade_timeout():
    sig = _FakeSig("AAPL", date(2025, 1, 1), entry=100, stop=95, target=120)
    bars = _bars(date(2025, 1, 1), [101, 102, 103])
    trade = _simulate_trade(sig, bars, hold_days=3)
    assert trade is not None
    assert trade["outcome"] == "timeout"


def test_simulate_trade_no_future_bars():
    sig = _FakeSig("AAPL", date(2025, 1, 5), entry=100, stop=95, target=110)
    bars = _bars(date(2025, 1, 1), [101])
    trade = _simulate_trade(sig, bars, hold_days=5)
    assert trade is None


def test_empty_result_structure():
    r = _empty_result("pullback", date(2025, 1, 1), date(2025, 3, 31), 90, 10, 70.0)
    assert r["total_signals"] == 0
    assert r["win_rate"] == 0.0
    assert r["trades"] == []


def test_run_backtest_no_data_returns_empty():
    result = run_backtest("double_bottom", period_days=1, hold_days=5, min_score=99.9)
    assert result["pattern_name"] == "double_bottom"
    assert isinstance(result["total_signals"], int)
    assert isinstance(result["trades"], list)
    assert "win_rate" in result
