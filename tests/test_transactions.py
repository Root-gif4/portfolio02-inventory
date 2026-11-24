"""入出庫・在庫の計算・取消・棚卸（UT-07〜16）。"""

from datetime import date, timedelta

import pytest
from conftest import TODAY

from inventory import service
from inventory.errors import InventoryError
from inventory.models import ADJUST, IN, OUT

D = lambda n: TODAY - timedelta(days=n)  # noqa: E731  n 日前


# UT-07 入庫・出庫で在庫が増減する
def test_in_out_balance(s, product):
    service.record_in(s, product.id, 10, D(5), "仕入先A", today=TODAY)
    service.record_out(s, product.id, 4, D(3), "店頭", today=TODAY)
    assert service.balance(s, product.id) == 6
    assert service.balance(s, product.id, as_of=D(4)) == 10
    assert service.balance(s, product.id, as_of=D(6)) == 0


# UT-08 入力チェック（数量・日付）
@pytest.mark.parametrize("qty, d, message", [
    (0, TODAY, "1〜1,000,000"),
    (-3, TODAY, "1〜1,000,000"),
    ("2.5", TODAY, "整数"),
    (1_000_001, TODAY, "1〜1,000,000"),
    (1, TODAY + timedelta(days=1), "未来の日付"),
    (1, date(1999, 12, 31), "2000-01-01 以降"),
    (1, "2026/13/01", "読めません"),
])
def test_entry_validation(s, product, qty, d, message):
    with pytest.raises(InventoryError, match=message):
        service.record_in(s, product.id, qty, d, today=TODAY)


def test_date_string_and_fullwidth_quantity(s, product):
    t = service.record_in(s, product.id, "１２", "2026/11/01", today=TODAY)
    assert (t.quantity, t.txn_date) == (12, date(2026, 11, 1))


# UT-09 在庫より多くは出庫できない
def test_cannot_go_negative(s, product):
    service.record_in(s, product.id, 5, D(2), today=TODAY)
    with pytest.raises(InventoryError, match="在庫が足りません"):
        service.record_out(s, product.id, 6, TODAY, today=TODAY)
    service.record_out(s, product.id, 5, TODAY, today=TODAY)  # ちょうど 0 は OK
    assert service.balance(s, product.id) == 0


# UT-10 過去の日付の出庫：その後の在庫も確かめる
def test_past_dated_out_checks_future(s, product):
    service.record_in(s, product.id, 10, D(10), today=TODAY)
    service.record_out(s, product.id, 8, D(2), today=TODAY)
    # 5 日前の時点では 10 個あるが、5 個出すと 2 日前に 10-5-8 = -3 になる
    with pytest.raises(InventoryError, match="そのあとの出庫"):
        service.record_out(s, product.id, 5, D(5), today=TODAY)
    service.record_out(s, product.id, 2, D(5), today=TODAY)
    assert service.balance(s, product.id) == 0


def test_past_dated_out_before_first_in(s, product):
    service.record_in(s, product.id, 10, D(3), today=TODAY)
    with pytest.raises(InventoryError, match="在庫が足りません"):
        service.record_out(s, product.id, 1, D(4), today=TODAY)


def test_same_day_order_uses_end_of_day(s, product):
    """同じ日の入庫より前に登録した出庫でも、その日の終わりで足りれば OK（登録順の都合で断らない）。"""
    service.record_in(s, product.id, 5, D(1), today=TODAY)
    service.record_out(s, product.id, 5, D(1), today=TODAY)
    assert service.balance(s, product.id, as_of=D(1)) == 0


# UT-11 取消
def test_reverse_in_and_out(s, product):
    t_in = service.record_in(s, product.id, 10, D(5), today=TODAY)
    t_out = service.record_out(s, product.id, 3, D(1), today=TODAY)
    rev = service.reverse_transaction(s, t_out.id, "入力ミス")
    assert (rev.kind, rev.delta, rev.txn_date, rev.reversal_of) == (OUT, 3, t_out.txn_date, t_out.id)
    assert service.balance(s, product.id) == 10
    assert service.reverse_transaction(s, t_in.id).delta == -10
    assert service.balance(s, product.id) == 0


def test_reverse_rules(s, product):
    t = service.record_in(s, product.id, 10, D(5), today=TODAY)
    rev = service.reverse_transaction(s, t.id)
    with pytest.raises(InventoryError, match="もう取り消されています"):
        service.reverse_transaction(s, t.id)
    with pytest.raises(InventoryError, match="取消の取引は取り消せません"):
        service.reverse_transaction(s, rev.id)


def test_reverse_in_blocked_if_already_used(s, product):
    """入庫を取り消すと、その後の出庫の分が足りなくなる場合は取り消せない。"""
    t = service.record_in(s, product.id, 10, D(5), today=TODAY)
    service.record_out(s, product.id, 4, D(1), today=TODAY)
    with pytest.raises(InventoryError, match="在庫が"):
        service.reverse_transaction(s, t.id)


# UT-12 棚卸調整
def test_adjust(s, product):
    service.record_in(s, product.id, 10, D(5), today=TODAY)
    t = service.record_adjust(s, product.id, 7, D(1), "破損", today=TODAY)
    assert (t.kind, t.quantity, t.delta) == (ADJUST, 3, -3)
    assert service.balance(s, product.id) == 7
    up = service.record_adjust(s, product.id, 9, TODAY, today=TODAY)
    assert up.delta == 2
    with pytest.raises(InventoryError, match="調整は要りません"):
        service.record_adjust(s, product.id, 9, TODAY, today=TODAY)


def test_adjust_in_past_cannot_break_later_outs(s, product):
    service.record_in(s, product.id, 10, D(5), today=TODAY)
    service.record_out(s, product.id, 8, D(1), today=TODAY)
    with pytest.raises(InventoryError, match="そのあとの出庫"):
        service.record_adjust(s, product.id, 2, D(3), today=TODAY)  # 2 にすると 1 日前に -6


# UT-13 DB の制約（画面を通さずに入れても弾く）
def test_db_constraints(s, product):
    from sqlalchemy.exc import IntegrityError
    from inventory.models import StockTransaction
    for bad in (dict(kind=IN, quantity=5, delta=-5), dict(kind=OUT, quantity=0, delta=0), dict(kind="XX", quantity=1, delta=1)):
        with pytest.raises(IntegrityError):
            with s.begin_nested():
                s.add(StockTransaction(product_id=product.id, txn_date=TODAY, **bad))
                s.flush()


# UT-14 在庫一覧・アラート
def test_stock_table_and_alerts(s, cat, product):
    p2 = service.create_product(s, service.ProductInput(code="TS-002", name="靴下", category_id=cat.id, reorder_point=10,
                                                        unit_price=300))
    p3 = service.create_product(s, service.ProductInput(code="TS-003", name="帽子", category_id=cat.id, reorder_point=2))
    service.record_in(s, product.id, 20, D(3), today=TODAY)
    service.record_in(s, p2.id, 8, D(3), today=TODAY)
    df = service.stock_table(s).set_index("商品コード")
    assert df.loc["TS-001", "在庫数"] == 20 and df.loc["TS-001", "在庫金額"] == 20_000
    assert list(df["状態"]) == ["適正", "要発注", "在庫切れ"]
    al = service.alerts(s)
    assert list(al["商品コード"]) == ["TS-003", "TS-002"]  # 在庫切れが先
    assert list(al["不足数"]) == [2, 2]
    past = service.stock_table(s, as_of=D(4)).set_index("商品コード")
    assert past.loc["TS-001", "在庫数"] == 0


# UT-15 検索
def test_search_transactions(s, product):
    t1 = service.record_in(s, product.id, 10, D(10), "みなと商事", today=TODAY)
    service.record_out(s, product.id, 2, D(5), "店頭", "セール_50%", today=TODAY)
    assert t1.id
    df = service.search_transactions(s, service.TxnFilter(date_from=D(6)))
    assert list(df["種類"]) == ["出庫"]
    assert len(service.search_transactions(s, service.TxnFilter(keyword="みなと"))) == 1
    assert len(service.search_transactions(s, service.TxnFilter(keyword="50%"))) == 1  # % をそのまま探せる
    assert len(service.search_transactions(s, service.TxnFilter(keyword="5%"))) == 0
    assert len(service.search_transactions(s, service.TxnFilter(kinds=(IN,)))) == 1
    t3 = service.record_out(s, product.id, 1, D(1), today=TODAY)
    service.reverse_transaction(s, t3.id)
    all_rows = service.search_transactions(s)
    assert set(all_rows["状態"]) == {"", "取消", "取消済み"}
    assert len(service.search_transactions(s, service.TxnFilter(hide_reversed=True))) == 2


# UT-16 月別集計（取消は元の月で差し引く）
def test_monthly_summary(s, product):
    service.record_in(s, product.id, 10, date(2026, 10, 5), today=TODAY)
    service.record_out(s, product.id, 4, date(2026, 10, 20), today=TODAY)
    wrong = service.record_out(s, product.id, 3, date(2026, 11, 2), today=TODAY)
    service.reverse_transaction(s, wrong.id)
    service.record_adjust(s, product.id, 5, date(2026, 11, 10), today=TODAY)
    df = service.monthly_summary(s).set_index("月")
    assert df.loc["2026-10", ["入庫数", "出庫数", "差引", "入庫金額"]].tolist() == [10, 4, 6, 10_000]
    assert df.loc["2026-11", ["入庫数", "出庫数", "棚卸調整", "差引"]].tolist() == [0, 0, -1, -1]
    assert df["差引"].sum() == service.balance(s, product.id)
