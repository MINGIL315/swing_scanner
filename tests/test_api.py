"""FastAPI 엔드포인트 통합 테스트."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from scanner.api.main import app

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_markets_summary_returns_200():
    r = client.get("/api/markets/summary")
    assert r.status_code == 200
    body = r.json()
    assert "scan_date" in body
    assert "total_signals" in body
    assert "kr" in body
    assert "us" in body
    assert "pattern_distribution" in body


def test_scan_results_default():
    r = client.get("/api/scan-results")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_scan_results_filter_invalid_score():
    r = client.get("/api/scan-results?min_score=-1")
    assert r.status_code == 422


def test_scan_results_filter_pattern():
    r = client.get("/api/scan-results?pattern=golden_cross&top=10")
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list)
    for row in rows:
        assert row["pattern_name"] == "golden_cross"


def test_patterns_list():
    r = client.get("/api/patterns")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    names = [p["pattern_name"] for p in data]
    assert "double_bottom" in names
    assert "golden_cross" in names
    assert "box_breakout" in names
    assert "pullback" in names


def test_patterns_stats_valid():
    r = client.get("/api/patterns/golden_cross/stats?period=30")
    assert r.status_code == 200
    body = r.json()
    assert "total_signals" in body
    assert "avg_confidence" in body


def test_patterns_stats_invalid():
    r = client.get("/api/patterns/unknown_pattern/stats")
    assert r.status_code in (404, 422)


def test_stocks_ohlcv_not_found():
    r = client.get("/api/stocks/NONEXIST_TICKER_XYZ/ohlcv")
    assert r.status_code == 404


def test_stocks_analysis_not_found():
    r = client.get("/api/stocks/NONEXIST_TICKER_XYZ/analysis")
    assert r.status_code == 404


def test_backtest_invalid_pattern():
    r = client.post(
        "/api/backtest/run",
        json={"pattern_name": "not_a_pattern", "period_days": 30},
    )
    assert r.status_code == 422


def test_backtest_valid_request():
    r = client.post(
        "/api/backtest/run",
        json={
            "pattern_name": "double_bottom",
            "period_days": 30,
            "hold_days": 5,
            "min_score": 70.0,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["pattern_name"] == "double_bottom"
    assert "total_signals" in body
    assert "win_rate" in body
    assert "profit_factor" in body
    assert isinstance(body["trades"], list)
