"""DB 초기화 / 마이그레이션 진입점.

사용법::

    python -m scanner.db.migrations

이 명령은 다음을 수행한다:

1. ``data/`` 디렉토리 생성 (이미 있으면 스킵)
2. SQLite WAL 모드 활성화 (동시 읽기 성능 ↑)
3. ``Base.metadata`` 의 모든 테이블 생성 (``CREATE TABLE IF NOT EXISTS``)
4. 생성된 테이블 목록을 출력
"""
from __future__ import annotations

import sys

from sqlalchemy import inspect, text

from scanner.config import setup_logger, settings
from scanner.db.models import Base
from scanner.db.session import engine


def init_database() -> list[str]:
    """DB 파일을 초기화하고 모든 테이블을 생성한다.

    Returns:
        생성된 테이블 이름 목록 (정렬된 상태).
    """
    setup_logger()
    from loguru import logger

    settings.ensure_directories()

    logger.info("DB 경로: {}", settings.DB_PATH)

    # 1. WAL 모드 활성화
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA journal_mode=WAL"))
        mode = result.scalar()
        logger.info("SQLite journal_mode = {}", mode)
        conn.execute(text("PRAGMA synchronous=NORMAL"))
        conn.commit()

    # 2. 테이블 생성
    Base.metadata.create_all(engine)

    # 3. 검증 — 실제 생성된 테이블 조회
    inspector = inspect(engine)
    tables = sorted(inspector.get_table_names())
    logger.info("생성된 테이블 ({}개): {}", len(tables), tables)

    return tables


def main() -> int:
    """CLI 진입점."""
    try:
        tables = init_database()
    except Exception as exc:  # noqa: BLE001
        # 부트스트랩 단계라 어떤 예외든 사용자에게 그대로 보여준다
        print(f"[ERROR] DB 초기화 실패: {exc}", file=sys.stderr)
        return 1

    print(f"OK — {len(tables)}개 테이블 생성 완료")
    for t in tables:
        print(f"  - {t}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
