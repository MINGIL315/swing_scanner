"""SQLAlchemy 엔진 + 세션 팩토리.

SQLite는 단일 파일 DB이며, 여기서는 ``check_same_thread=False`` 로 멀티스레드
fetch와 호환되도록 설정한다 (실제 동시 쓰기는 한 시점에 1개로 제한된다).
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from scanner.config import settings


def _build_engine() -> Engine:
    """SQLite 엔진을 생성한다.

    - WAL 모드 활성화는 ``migrations.init_database()`` 에서 처리.
    - ``foreign_keys=ON`` PRAGMA 를 매 연결마다 켠다 (SQLite 기본값이 OFF).
    """
    url = f"sqlite:///{settings.DB_PATH}"
    engine = create_engine(
        url,
        echo=False,
        future=True,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


engine: Engine = _build_engine()

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=Session,
)


@contextmanager
def get_session() -> Iterator[Session]:
    """트랜잭션 컨텍스트 매니저.

    예::

        with get_session() as session:
            session.add(obj)
            # 컨텍스트 종료 시 자동 commit, 예외 발생 시 rollback
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


__all__ = ["engine", "SessionLocal", "get_session"]
