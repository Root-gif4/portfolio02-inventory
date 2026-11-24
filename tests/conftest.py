import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from inventory import service  # noqa: E402
from inventory.db import init_db, make_engine, make_session_factory, session_scope  # noqa: E402

TODAY = date(2026, 11, 23)


@pytest.fixture
def factory():
    engine = make_engine(":memory:")
    init_db(engine)
    yield make_session_factory(engine)
    engine.dispose()


@pytest.fixture
def s(factory):
    """1 つのテストの中で使うセッション（最後に確定する）。"""
    with session_scope(factory) as session:
        yield session


@pytest.fixture
def cat(s):
    return service.create_category(s, "衣料")


@pytest.fixture
def product(s, cat):
    return service.create_product(s, service.ProductInput(code="TS-001", name="Tシャツ", category_id=cat.id,
                                                          unit="枚", unit_price=1000, reorder_point=5))
