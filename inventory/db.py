"""DB（SQLite）への接続を1か所で作る。

- 外部キーを有効にする（SQLite は接続ごとに PRAGMA foreign_keys=ON が必要）
- 書き込みは BEGIN IMMEDIATE で始める。在庫の確認 → 取引の追加 の間に、
  ほかの書き込みが割り込まないようにするため（「確認したのに在庫がマイナス」を防ぐ）
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

DB_FILENAME = "inventory.db"


def default_home() -> Path:
    """データの置き場所。環境変数 INVENTORY_HOME で変えられる（既定はプロジェクトの data/）。"""
    env = os.environ.get("INVENTORY_HOME")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[1] / "data"


def make_engine(db_path: Path | str | None = None) -> Engine:
    """db_path が ":memory:" ならメモリ上の DB（テスト用）。"""
    if db_path is None:
        home = default_home()
        home.mkdir(parents=True, exist_ok=True)
        db_path = home / DB_FILENAME
    if str(db_path) == ":memory:":
        from sqlalchemy.pool import StaticPool
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    else:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(f"sqlite:///{Path(db_path).as_posix()}",
                               connect_args={"check_same_thread": False, "timeout": 15})

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record):
        # pysqlite の自動トランザクションを止め、BEGIN を自分で出す（SQLAlchemy の推奨手順）
        dbapi_conn.isolation_level = None
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL") if str(db_path) != ":memory:" else None
        cur.close()

    @event.listens_for(engine, "begin")
    def _on_begin(conn):
        conn.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """成功したら確定（commit）、途中で失敗したらすべて取り消す（rollback）。"""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
