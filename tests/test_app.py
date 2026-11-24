"""画面の結合テスト（Streamlit の AppTest で、ブラウザなしに画面を動かす）。IT-01〜08。"""

import os
from datetime import date

import pytest
from conftest import ROOT

from streamlit.testing.v1 import AppTest

APP = str(ROOT / "app" / "streamlit_app.py")


@pytest.fixture
def at(tmp_path, monkeypatch):
    monkeypatch.setenv("INVENTORY_HOME", str(tmp_path))
    monkeypatch.chdir(ROOT)
    from common import _factory, logger  # キャッシュを空にして、このテスト用の DB を使う
    _factory.clear()
    logger.clear()
    app = AppTest.from_file(APP, default_timeout=60)
    app.run()
    yield app
    _factory.clear()


def no_exception(app):
    assert not app.exception, [e.value for e in app.exception]


def pick_first(at, key):
    """選択欄の 1 つ目を選ぶ（値が番号で、表示は文字の欄用）。"""
    sb = at.selectbox(key=key)
    first = sb.options[0]
    value = next(i for i in range(1, 100_000) if sb.format_func(i) == first)
    return sb.set_value(value)


def seeded(at):
    next(b for b in at.button if b.label == "見本データを入れる").click().run()
    no_exception(at)
    return at


# IT-01 空のとき → 見本データ → ダッシュボード
def test_empty_then_seed(at):
    no_exception(at)
    assert any("まだデータがありません" in i.value for i in at.info)
    seeded(at)
    assert any("見本データを入れました" in s.value for s in at.success)
    labels = [m.label for m in at.metric]
    assert labels[:4] == ["商品数", "在庫金額", "在庫切れ", "要発注"]
    assert at.metric[0].value == "12"


# IT-02 すべてのページがエラーなく開く
@pytest.mark.parametrize("page", ["entry", "stock", "history", "monthly", "products", "categories", "csv_io",
                                  "integrity", "backup", "dashboard"])
def test_every_page_opens(at, page):
    seeded(at)
    at.switch_page(f"views/{page}.py").run()
    no_exception(at)
    assert at.title and not at.error


# IT-03 入庫 → 在庫が増える。出庫しすぎはボタンが押せない
def test_entry_flow(at):
    seeded(at)
    at.switch_page("views/entry.py").run()
    pick_first(at, "entry_product").run()   # BG-101
    before = int(at.metric[0].value.split()[0].replace(",", ""))
    at.number_input(key="entry_qty").set_value(5).run()
    next(b for b in at.button if b.label == "入庫を登録する").click().run()
    no_exception(at)
    assert any("入庫を登録しました" in s.value for s in at.success)
    pick_first(at, "entry_product").run()
    assert int(at.metric[0].value.split()[0].replace(",", "")) == before + 5

    at.segmented_control(key="entry_mode").set_value("出庫").run()
    at.number_input(key="entry_qty").set_value(999_999).run()
    btn = next(b for b in at.button if b.label == "出庫を登録する")
    assert btn.disabled
    assert any("マイナス" in e.value for e in at.error)


# IT-04 取引の取消
def test_reverse_from_history(at):
    seeded(at)
    at.switch_page("views/history.py").run()
    pick_first(at, "rev_target").run()                  # 取り消す取引（一覧のいちばん上）
    at.checkbox(key="rev_sure").check().run()
    next(b for b in at.button if b.label == "取り消す").click().run()
    no_exception(at)
    assert any("を取り消しました" in s.value for s in at.success)


# IT-05 商品の追加（入力の誤りは理由を表示）
def test_add_product(at):
    seeded(at)
    at.switch_page("views/products.py").run()
    at.text_input(key="add_code").set_value("NEW-01")
    at.text_input(key="add_name").set_value("新しい商品")
    next(b for b in at.button if b.label == "この内容で追加する").click().run()
    no_exception(at)
    assert any("新しい商品" in s.value for s in at.success)
    at.text_input(key="add_code").set_value("NEW-01")
    at.text_input(key="add_name").set_value("重複")
    next(b for b in at.button if b.label == "この内容で追加する").click().run()
    assert any("もう使われています" in e.value for e in at.error)


# IT-06 整合性チェックの画面
def test_integrity_page(at):
    seeded(at)
    at.switch_page("views/integrity.py").run()
    next(b for b in at.button if b.label == "チェックする").click().run()
    no_exception(at)
    assert any("問題はありませんでした" in s.value for s in at.success)


# IT-07 想定外のエラーは受付番号だけを出す（内部の情報を出さない）
def test_unexpected_error_shows_ticket_only(at, monkeypatch, tmp_path):
    seeded(at)
    from inventory import service

    def boom(*a, **k):
        raise RuntimeError("SECRET-INTERNAL-PATH C:\\secret\\db")

    monkeypatch.setattr(service, "record_in", boom)
    at.switch_page("views/entry.py").run()
    pick_first(at, "entry_product").run()
    next(b for b in at.button if b.label == "入庫を登録する").click().run()
    shown = " ".join(e.value for e in at.error)
    assert "受付番号" in shown and "SECRET" not in shown
    log = (tmp_path / "logs" / "app.log").read_text(encoding="utf-8")
    assert "SECRET-INTERNAL-PATH" in log


# IT-08 バックアップの画面
def test_backup_page(at, tmp_path):
    seeded(at)
    at.switch_page("views/backup.py").run()
    next(b for b in at.button if b.label == "今すぐバックアップする").click().run()
    no_exception(at)
    assert list((tmp_path / "backups").glob("inventory_*.db"))
