"""패턴 탐지 공통 인터페이스."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd


@dataclass
class PatternResult:
    """패턴 탐지 결과.

    Attributes:
        pattern_name    : 패턴 식별자 (e.g., 'double_bottom').
        ticker          : 종목 코드.
        detected_at     : 탐지 기준일 (마지막 데이터 날짜).
        entry_price     : 권장 진입가.
        stop_loss       : 손절가.
        target_price    : 목표가.
        risk_reward_ratio: 목표가 / 손절 폭 비율 ((target - entry) / (entry - stop)).
        raw_score       : 패턴 명확도 점수 (0~100).
        details         : 탐지에 사용된 수치 원본 (디버깅용).
    """

    pattern_name: str
    ticker: str
    detected_at: date
    entry_price: float
    stop_loss: float
    target_price: float
    risk_reward_ratio: float
    raw_score: float
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class EntrySignal:
    """진입 타이밍 신호 평가 결과.

    Attributes:
        strength : 진입 강도 점수 (0~100).
        signals  : 개별 신호 컴포넌트 이름 → True/False.
    """

    strength: float
    signals: dict[str, bool] = field(default_factory=dict)


class PatternDetector(ABC):
    """모든 패턴 탐지기의 추상 기반 클래스.

    서브클래스는 name, display_name 을 클래스 속성으로 선언하고
    detect() 와 entry_signal() 을 구현해야 한다.
    """

    name: str          # 패턴 식별자 (snake_case)
    display_name: str  # 한국어 표시명

    @abstractmethod
    def detect(
        self,
        df: pd.DataFrame,
        ticker: str = "",
    ) -> PatternResult | None:
        """일봉 OHLCV DataFrame에서 패턴을 탐지한다.

        Args:
            df    : open/high/low/close/volume 컬럼을 가진 일봉 DataFrame.
                    최신 행이 마지막 행이어야 한다.
            ticker: 종목 코드 (결과 레이블용).

        Returns:
            패턴이 탐지되면 PatternResult, 없으면 None.
        """

    @abstractmethod
    def entry_signal(
        self,
        df: pd.DataFrame,
        intraday_df: pd.DataFrame | None = None,
    ) -> EntrySignal:
        """진입 타이밍 신호를 평가한다.

        Args:
            df          : 일봉 DataFrame.
            intraday_df : 60분봉 DataFrame (없으면 일봉으로 대리 평가).

        Returns:
            EntrySignal 인스턴스.
        """
