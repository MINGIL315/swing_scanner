"""FastAPI 애플리케이션 엔트리포인트.

실행:
    uvicorn scanner.api.main:app --host 127.0.0.1 --port 8000 --reload
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from scanner.api.routers import backtest, markets, patterns, scan_results, stocks
from scanner.config import settings

app = FastAPI(
    title="Swing Scanner API",
    description="스윙매매 차트 발굴 시스템 REST API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — 로컬 전용
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:8000",
        "http://127.0.0.1",
        "http://127.0.0.1:8000",
        "null",  # file:// 로컬 HTML 오픈 허용
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# 정적 파일 (web/ 폴더)
_web_dir = settings.BASE_DIR / "web"
if _web_dir.exists():
    app.mount("/web", StaticFiles(directory=str(_web_dir)), name="web")

# 라우터 등록
app.include_router(scan_results.router, prefix="/api")
app.include_router(stocks.router, prefix="/api")
app.include_router(patterns.router, prefix="/api")
app.include_router(markets.router, prefix="/api")
app.include_router(backtest.router, prefix="/api")


@app.get("/api/health", tags=["health"])
def health() -> dict:
    """서버 상태 확인."""
    return {"status": "ok", "version": "1.0.0"}
