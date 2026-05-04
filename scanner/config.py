"""전역 설정 + 패턴 임계값 상수.

이 모듈은 프로젝트 전반에서 사용되는 경로, 임계값, 가중치, 필터 기준을
한 곳에 모아 관리한다. 매직 넘버를 코드 곳곳에 흩어 두지 않는 것이 목적이다.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

# .env 자동 로드 (있으면)
load_dotenv()


# ---------------------------------------------------------------------------
# 패턴 임계값 상수 (CLAUDE.md §5의 정의를 코드로)
# ---------------------------------------------------------------------------

# 쌍바닥 (Double Bottom)
DOUBLE_BOTTOM_LOOKBACK_DAYS: int = 60          # 탐색 구간
DOUBLE_BOTTOM_LOW_TOLERANCE_PCT: float = 0.03  # 두 저점 간 허용 가격 차이 (±3%)
DOUBLE_BOTTOM_MIN_LOWS: int = 2                # 최소 저점 개수
DOUBLE_BOTTOM_MAX_LOWS: int = 3                # 최대 저점 개수
DOUBLE_BOTTOM_NECKLINE_GAIN_PCT: float = 0.05  # 목선이 저점 대비 +5% 이상 위

# 골든크로스 (Golden Cross)
GOLDEN_CROSS_FAST_MA: int = 20                 # 단기 이동평균 (일)
GOLDEN_CROSS_SLOW_MA: int = 60                 # 장기 이동평균 (일)
GOLDEN_CROSS_RECENT_DAYS: int = 5              # 최근 N일 내 크로스 발생
GOLDEN_CROSS_VOLUME_RATIO: float = 1.2         # 돌파일 거래량 / 20일 평균

# 박스권 돌파 (Box Breakout)
BOX_BREAKOUT_MIN_DAYS: int = 30                # 박스 형성 최소 일수
BOX_BREAKOUT_MAX_DAYS: int = 60                # 박스 형성 최대 일수
BOX_BREAKOUT_RANGE_PCT: float = 0.10           # 박스 폭 (±10%)
BOX_BREAKOUT_RECENT_DAYS: int = 3              # 최근 N일 내 돌파
BOX_BREAKOUT_BREAK_PCT: float = 0.01           # 박스 상단 대비 +1% 이상
BOX_BREAKOUT_VOLUME_RATIO: float = 1.5         # 돌파일 거래량 / 20일 평균

# 눌림목 (Pullback)
PULLBACK_MA_NEAR_PCT: float = 0.02             # 20/60일선 ±2% 범위
PULLBACK_VOLUME_LOOKBACK: int = 5              # 거래량 비교용 평균 일수

# 공통 이동평균선 (정배열 검사용)
MA_SHORT: int = 5
MA_MEDIUM: int = 20
MA_LONG: int = 60
MA_WEEKLY_TREND: int = 20                      # 주봉 추세선


# ---------------------------------------------------------------------------
# 신뢰도 점수 가중치 (합계 1.0)
# ---------------------------------------------------------------------------

CONFIDENCE_WEIGHTS: dict[str, float] = {
    "weekly_trend": 0.30,    # 주봉 추세 일치
    "pattern_clarity": 0.25, # 패턴 명확도
    "volume": 0.20,          # 거래량
    "ma_alignment": 0.15,    # 이평선 정배열
    "rsi": 0.10,             # RSI 정상 범위
}

CONFIDENCE_THRESHOLD: float = 70.0  # 최종 리포트 채택 점수 (0~100)


# ---------------------------------------------------------------------------
# 거래량 필터 (Liquidity)
# ---------------------------------------------------------------------------

MIN_AVG_TRADING_VALUE_KRW: float = 5_000_000_000        # 일평균 거래대금 50억원
MIN_AVG_TRADING_VALUE_USD: float = 50_000_000           # 일평균 거래대금 5천만 USD
LIQUIDITY_LOOKBACK_DAYS: int = 20                       # 평균 산출 구간
RECENT_VOLUME_LOOKBACK_DAYS: int = 5                    # 최근 N일 평균 거래량 비교


# ---------------------------------------------------------------------------
# 재무 필터 (Fundamental)
# ---------------------------------------------------------------------------

MIN_MARKET_CAP_KRW: float = 100_000_000_000   # 시가총액 1000억원
MIN_MARKET_CAP_USD: float = 1_000_000_000     # 시가총액 10억 USD
MIN_PER: float = 0.0                          # PER > 0 (적자 제외)
MAX_DEBT_RATIO_KR: float = 200.0              # 부채비율 < 200%


# ---------------------------------------------------------------------------
# 데이터 fetch 동시성 / 재시도
# ---------------------------------------------------------------------------

FETCH_MAX_WORKERS: int = 5
FETCH_RETRY_MAX: int = 3
FETCH_RETRY_BACKOFF_BASE: float = 2.0          # exponential: base ** attempt 초
FETCH_TIMEOUT_SECONDS: float = 30.0


# ---------------------------------------------------------------------------
# Settings 클래스 (경로 + 환경 변수)
# ---------------------------------------------------------------------------

BASE_DIR: Path = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    """프로젝트 전역 설정 (경로 + 환경 변수).

    경로는 모두 ``pathlib.Path`` 로 다루며, 인스턴스화 시점에
    필요한 디렉토리를 자동 생성한다.
    """

    # 경로
    BASE_DIR: Path = BASE_DIR
    DATA_DIR: Path = BASE_DIR / "data"
    DB_PATH: Path = BASE_DIR / "data" / "scanner.db"
    LOG_DIR: Path = BASE_DIR / "logs"
    REPORTS_DIR: Path = BASE_DIR / "data" / "reports"
    EXPORTS_DIR: Path = BASE_DIR / "data" / "exports"

    # 환경 변수
    log_level: str = field(
        default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper()
    )
    api_host: str = field(
        default_factory=lambda: os.getenv("API_HOST", "127.0.0.1")
    )
    api_port: int = field(
        default_factory=lambda: int(os.getenv("API_PORT", "8000"))
    )

    def ensure_directories(self) -> None:
        """런타임에 필요한 디렉토리를 생성한다 (이미 있으면 스킵)."""
        for d in (self.DATA_DIR, self.LOG_DIR, self.REPORTS_DIR, self.EXPORTS_DIR):
            d.mkdir(parents=True, exist_ok=True)


# 싱글톤 인스턴스
settings = Settings()
settings.ensure_directories()


# ---------------------------------------------------------------------------
# 로깅 설정
# ---------------------------------------------------------------------------

_LOGGER_INITIALIZED = False


def setup_logger(log_level: str | None = None) -> None:
    """``loguru`` 로거를 표준 출력 + 파일에 동시 기록하도록 설정한다.

    Args:
        log_level: 명시적으로 설정할 로그 레벨. ``None`` 이면 ``settings.log_level`` 사용.
    """
    global _LOGGER_INITIALIZED
    if _LOGGER_INITIALIZED:
        return

    level = (log_level or settings.log_level).upper()

    # 기본 핸들러 제거 후 재구성
    logger.remove()

    # 콘솔 (Windows cp949 회피용 UTF-8 강제)
    logger.add(
        sys.stderr,
        level=level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        enqueue=True,
        backtrace=True,
        diagnose=False,
    )

    # 파일 (날짜별 로테이션, UTF-8)
    log_file = settings.LOG_DIR / "scanner_{time:YYYY-MM-DD}.log"
    logger.add(
        str(log_file),
        level=level,
        rotation="00:00",
        retention="30 days",
        encoding="utf-8",
        format=(
            "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | "
            "{name}:{function}:{line} | {message}"
        ),
        enqueue=True,
    )

    _LOGGER_INITIALIZED = True
    logger.debug("logger initialized (level={})", level)
