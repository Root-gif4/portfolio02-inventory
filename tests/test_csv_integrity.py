"""CSV の取り込み・書き出し、整合性チェック、バックアップ、見本データ（UT-17〜24）。"""

import csv
import io
import sqlite3
from datetime import date

import pytest
from conftest import TODAY
from sqlalchemy import text

from inventory import backup, csvio, integrity, seed, service
from inventory.errors import InventoryError


def csv_bytes(rows, encoding="utf-8-sig"):
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\r\n").writerows(rows)
    return buf.getvalue().encode(encoding)


# UT-17 書き出し：CSV インジェクション対策・BOM
@pytest.mark.parametrize("value, expected", [
    ("=SUM(A1)", "'=SUM(A1)"), ("+1+1", "'+1+1"), ("@cmd", "'@cmd"), ("-500", "-500"), ("-x", "'-x"),
    ("普通", "普通"), ("", ""), (12, 12),
])
def test_sanitize_cell(value, expected):
    assert csvio.sanitize_cell(value) == expected


def test_export_products_is_excel_friendly(s, product):
    product.name = "=HYPERLINK(\"http://example.com\")"
    data = csvio.export_products(s)
    assert data.startswith(b"\xef\xbb\xbf") and b"\r\n" in data
    assert "'=HYPERLINK" in data.decode("utf-8-sig")


# UT-18 商品の取り込み
def test_import_products_dry_run_then_save(s, cat, product):
    data = csv_bytes([["商品コード", "商品名", "カテゴリ", "単位", "仕入単価", "発注点", "メモ"],
                      ["TS-001", "Tシャツ（名前変更）", "衣料", "枚", "1,100", "5", ""],
                      ["NB-001", "ノート", "文具", "冊", "300", "10", ""]])
    r = csvio.import_products(s, data, dry_run=True)
    assert r.ok and (r.created, r.updated, r.saved) == (1, 1, False)
    assert service.find_product_by_code(s, "NB-001") is None          # 確認では保存しない
    assert [c.name for c in service.list_categories(s)] == ["衣料"]   # カテゴリも作らない
    r = csvio.import_products(s, data, dry_run=False)
    assert r.saved and service.find_product_by_code(s, "NB-001").category.name == "文具"
    assert service.get_product(s, product.id).unit_price == 1100


def test_import_products_all_or_nothing(s, cat):
    data = csv_bytes([["商品コード", "商品名", "カテゴリ"],
                      ["OK-001", "正しい行", "衣料"],
                      ["", "コードなし", "衣料"],
                      ["OK-001", "重複", "衣料"]], encoding="cp932")
    r = csvio.import_products(s, data, dry_run=False)
    assert not r.saved and r.encoding == "Shift_JIS"
    assert [row for row, _ in r.errors] == [3, 4]
    assert service.find_product_by_code(s, "OK-001") is None


@pytest.mark.parametrize("data, message", [
    (b"", "空です"),
    ("商品名,カテゴリ\r\nA,B\r\n".encode(), "必要な列がありません：商品コード"),
    (b"\x00\x01\x02", "バイナリ"),
    (b"\xff\xfe\xfa\x80\x81", "文字コード"),
    ("商品コード,商品コード,商品名,カテゴリ\r\n".encode(), "同じ名前の見出し"),
])
def test_import_bad_files(s, data, message):
    with pytest.raises(InventoryError, match=message):
        csvio.import_products(s, data)


def test_import_size_limit(s, monkeypatch):
    monkeypatch.setattr(csvio, "MAX_BYTES", 10)
    with pytest.raises(InventoryError, match="大きすぎます"):
        csvio.import_products(s, b"x" * 11)


# UT-19 入出庫の取り込み（在庫が足りるかも確かめる）
def test_import_transactions(s, product):
    good = csv_bytes([["取引日", "種類", "商品コード", "数量", "取引先", "メモ"],
                      ["2026-11-01", "入庫", "TS-001", "10", "A社", ""],
                      ["2026/11/02", "出庫", "ts-001", "4", "店頭", ""]])
    r = csvio.import_transactions(s, good, dry_run=True, today=TODAY)
    assert r.ok and r.created == 2 and service.balance(s, product.id) == 0
    r = csvio.import_transactions(s, good, dry_run=False, today=TODAY)
    assert r.saved and service.balance(s, product.id) == 6

    bad = csv_bytes([["取引日", "種類", "商品コード", "数量"],
                     ["2026-11-03", "出庫", "TS-001", "100"],     # 在庫が足りない
                     ["2026-11-03", "棚卸", "TS-001", "1"],       # 種類が違う
                     ["2026-11-03", "入庫", "XX-999", "1"],       # 商品がない
                     ["2099-01-01", "入庫", "TS-001", "1"],       # 未来
                     ["2026-11-03", "入庫", "TS-001", "1"]])      # これだけ正しい
    r = csvio.import_transactions(s, bad, dry_run=False, today=TODAY)
    assert not r.saved and [row for row, _ in r.errors] == [2, 3, 4, 5]
    assert service.balance(s, product.id) == 6  # 正しい行も保存しない


# UT-20 整合性チェック：正しいデータは全部 OK
def test_integrity_ok_on_seed(s):
    seed.seed(s, days=40, today=TODAY)
    results = integrity.run_checks(s, today=TODAY)
    assert len(results) == 8 and all(r.ok for r in results), [r.problems for r in results if not r.ok]


# UT-21 整合性チェック：DB を直接書き換えると見つける
def test_integrity_detects_tampering(s, product):
    t = service.record_in(s, product.id, 5, date(2026, 11, 1), today=TODAY)
    out = service.record_out(s, product.id, 5, date(2026, 11, 2), today=TODAY)
    rev = service.reverse_transaction(s, out.id)
    s.flush()
    # 制約をくぐって書き換える（DB を直接さわられた想定）
    s.execute(text("PRAGMA ignore_check_constraints = ON"))
    s.execute(text("UPDATE stock_transactions SET delta = 2 WHERE id = :i"), {"i": t.id})          # 入庫の数と合わない・マイナス
    s.execute(text("UPDATE stock_transactions SET txn_date = '2026-11-05' WHERE id = :i"), {"i": rev.id})  # 取消の日付違い
    s.execute(text("INSERT INTO stock_transactions (product_id, kind, quantity, delta, txn_date, partner, memo) "
                   "VALUES (:p, 'IN', 1, 1, '2027-01-01', '', '')"), {"p": product.id})        # 未来
    s.execute(text("PRAGMA ignore_check_constraints = OFF"))
    s.expire_all()
    bad = {r.name for r in integrity.run_checks(s, today=TODAY) if not r.ok}
    assert {"取引の向き", "取消の対応", "在庫のマイナス", "未来の日付"} <= bad


# UT-22 バックアップ
def test_backup(tmp_path):
    db = tmp_path / "inventory.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE t (x)")
    con.execute("INSERT INTO t VALUES (1)")
    con.commit()
    con.close()
    paths = [backup.create_backup(db, tmp_path / "b", keep=2) for _ in range(3)]
    files = backup.list_backups(tmp_path / "b")
    assert len(files) == 2 and files[0] == paths[-1]
    assert sqlite3.connect(files[0]).execute("SELECT x FROM t").fetchone() == (1,)
    with pytest.raises(FileNotFoundError):
        backup.create_backup(tmp_path / "none.db", tmp_path / "b")


# UT-23 見本データ
def test_seed_only_on_empty(s):
    stats = seed.seed(s, today=TODAY)
    assert stats["商品"] == 12 and stats["取引"] > 100
    statuses = set(service.stock_table(s)["状態"])
    assert {"在庫切れ", "要発注", "適正"} <= statuses
    with pytest.raises(InventoryError, match="空の DB"):
        seed.seed(s, today=TODAY)


# UT-24 ダッシュボードの数字
def test_dashboard_numbers(s, product):
    service.record_in(s, product.id, 3, TODAY, today=TODAY)
    n = service.dashboard_numbers(s)
    assert (n["商品数"], n["在庫数の合計"], n["在庫金額"], n["要発注"], n["取引件数"]) == (1, 3, 3000, 1, 1)


# IT-09 samples の CSV が説明どおりに動く（見本データ → 商品の追加 → 入出庫）
def test_sample_csv_files(s):
    from conftest import ROOT
    seed.seed(s, today=TODAY)
    samples = ROOT / "samples"
    r = csvio.import_products(s, (samples / "商品_追加.csv").read_bytes(), dry_run=False)
    assert r.saved and r.created == 5
    r = csvio.import_transactions(s, (samples / "入出庫_まとめて.csv").read_bytes(), dry_run=False, today=TODAY)
    assert r.saved and r.created == 10
    assert service.balance(s, service.find_product_by_code(s, "TS-003").id) == 34
    r = csvio.import_transactions(s, (samples / "入出庫_誤りあり.csv").read_bytes(), dry_run=True, today=TODAY)
    assert [row for row, _ in r.errors] == [3, 4, 5, 6, 7]