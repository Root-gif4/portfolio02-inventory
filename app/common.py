"""画面で共通に使う部品（DB の接続・エラーの出し方・数字の書き方・完了メッセージ）。"""

from __future__ import annotations

import logging
import sys
import uuid
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable, Iterator

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inventory.db import DB_FILENAME, default_home, init_db, make_engine, make_session_factory, session_scope  # noqa: E402
from inventory.errors import InventoryError  # noqa: E402
from inventory.models import KIND_LABELS  # noqa: E402
from inventory.service import STATUS_INACTIVE, STATUS_LOW, STATUS_OK, STATUS_OUT  # noqa: E402

STATUS_ICON = {STATUS_OUT: "🔴 在庫切れ", STATUS_LOW: "🟡 要発注", STATUS_OK: "🟢 適正", STATUS_INACTIVE: "⚪ 使用停止"}
KIND_ICON = {"入庫": "⬇️ 入庫", "出庫": "⬆️ 出庫", "棚卸調整": "📋 棚卸調整"}


@st.cache_resource
def _factory():
    home = default_home()
    engine = make_engine(home / DB_FILENAME)
    init_db(engine)
    return make_session_factory(engine)


def home_dir() -> Path:
    return default_home()


@st.cache_resource
def logger() -> logging.Logger:
    log = logging.getLogger("inventory.app")
    if not log.handlers:
        log_dir = default_home() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(log_dir / "app.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
    return log


@contextmanager
def db() -> Iterator:
    """読み書きの単位。途中で失敗したらすべて取り消される。"""
    with session_scope(_factory()) as s:
        yield s


def run_action(action: Callable, success: str | Callable | None = None, rerun: bool = True) -> bool:
    """書き込みの操作を実行する。成功したら次の画面表示で完了メッセージを出す。

    業務ルールのエラーは理由をそのまま、想定外のエラーは受付番号だけを出す（詳しくはログへ）。
    """
    try:
        with db() as s:
            value = action(s)
    except InventoryError as exc:
        st.error(str(exc), icon=":material/error:")
        return False
    except Exception:
        ticket = uuid.uuid4().hex[:8]
        logger().exception("想定外のエラー（受付番号 %s）", ticket)
        st.error(f"想定外のエラーが起きました。何も保存していません。（受付番号 {ticket}）\n\n"
                 "data/logs/app.log でこの受付番号を検索すると、詳しい内容が分かります。", icon=":material/error:")
        return False
    msg = success(value) if callable(success) else success
    if msg:
        st.session_state["_flash"] = msg
    if rerun:
        st.rerun()  # 一覧などを最新にする（try の外で呼ぶ）
    return True


def show_flash() -> None:
    msg = st.session_state.pop("_flash", None)
    if msg:
        st.success(msg, icon=":material/check_circle:")
        st.toast(msg, icon=":material/check_circle:")


def page_header(title: str, help_text: str) -> None:
    st.title(title)
    st.caption(help_text)
    show_flash()


def yen(v) -> str:
    return f"¥{int(v):,}"


def num(v) -> str:
    return f"{int(v):,}"


def product_label(p, stock: int | None = None) -> str:
    base = f"{p.code}　{p.name}"
    return base if stock is None else f"{base}（在庫 {stock:,}{p.unit}）"


__all__ = ["KIND_LABELS", "STATUS_ICON", "KIND_ICON", "db", "run_action", "page_header", "yen", "num",
           "product_label", "home_dir", "logger", "ROOT"]
