"""カテゴリ・商品マスタ（UT-01〜06）。"""

import pytest
from conftest import TODAY

from inventory import service
from inventory.errors import InventoryError, NotFoundError
from inventory.service import ProductInput


def P(cat_id, **kw):
    base = dict(code="TS-002", name="Tシャツ黒", category_id=cat_id, unit="枚", unit_price=1000, reorder_point=3)
    base.update(kw)
    return ProductInput(**base)


# UT-01 カテゴリ
def test_category_create_rename_duplicate(s):
    c = service.create_category(s, "  文具 ")
    assert c.name == "文具"
    with pytest.raises(InventoryError, match="もうあります"):
        service.create_category(s, "文具")
    with pytest.raises(InventoryError, match="入力してください"):
        service.create_category(s, "   ")
    other = service.create_category(s, "雑貨")
    with pytest.raises(InventoryError, match="もうあります"):
        service.rename_category(s, other.id, "文具")
    assert service.rename_category(s, other.id, "生活雑貨").name == "生活雑貨"


def test_category_deactivate_blocked_by_active_product(s, cat, product):
    with pytest.raises(InventoryError, match="使用中の商品"):
        service.set_category_active(s, cat.id, False)
    service.set_product_active(s, product.id, False)
    assert service.set_category_active(s, cat.id, False).active is False
    with pytest.raises(InventoryError, match="使用停止中"):
        service.create_product(s, P(cat.id))


# UT-02 商品の入力チェック
@pytest.mark.parametrize("kw, message", [
    ({"code": ""}, "商品コードを入力"),
    ({"code": "あいう"}, "半角の英数字"),
    ({"code": "A" * 21}, "20文字以内"),
    ({"name": ""}, "商品名を入力"),
    ({"name": "x" * 101}, "100文字以内"),
    ({"unit_price": -1}, "仕入単価"),
    ({"reorder_point": "abc"}, "整数"),
    ({"reorder_point": 1.5}, "整数"),
    ({"name": "a\x00b"}, "制御文字"),
])
def test_product_validation(s, cat, kw, message):
    with pytest.raises(InventoryError, match=message):
        service.create_product(s, P(cat.id, **kw))


def test_product_code_is_normalized(s, cat):
    p = service.create_product(s, P(cat.id, code="ｔｓ－００９", unit_price="１,２００"))
    assert p.code == "TS-009" and p.unit_price == 1200


# UT-03 重複・存在しない
def test_product_duplicate_code_and_missing(s, cat, product):
    with pytest.raises(InventoryError, match="もう使われています"):
        service.create_product(s, P(cat.id, code="ts-001"))
    with pytest.raises(NotFoundError):
        service.get_product(s, 9999)
    with pytest.raises(NotFoundError):
        service.create_product(s, P(9999))


# UT-04 商品コードの変更
def test_code_change_only_without_transactions(s, cat, product):
    service.update_product(s, product.id, P(cat.id, code="TS-100", name="Tシャツ"))
    service.record_in(s, product.id, 1, TODAY, today=TODAY)
    with pytest.raises(InventoryError, match="変えられません"):
        service.update_product(s, product.id, P(cat.id, code="TS-200"))
    # コード以外は変えられる
    assert service.update_product(s, product.id, P(cat.id, code="TS-100", name="新しい名前")).name == "新しい名前"


# UT-05 使用停止
def test_product_deactivate_requires_zero_stock(s, product):
    service.record_in(s, product.id, 3, TODAY, today=TODAY)
    with pytest.raises(InventoryError, match="在庫が 3枚 残っている"):
        service.set_product_active(s, product.id, False)
    service.record_out(s, product.id, 3, TODAY, today=TODAY)
    service.set_product_active(s, product.id, False)
    with pytest.raises(InventoryError, match="使用停止中のため"):
        service.record_in(s, product.id, 1, TODAY, today=TODAY)
    assert service.set_product_active(s, product.id, True).active


# UT-06 在庫の状態
@pytest.mark.parametrize("stock, reorder, active, status", [
    (0, 5, True, "在庫切れ"), (5, 5, True, "要発注"), (6, 5, True, "適正"), (1, 0, True, "適正"), (3, 5, False, "使用停止"),
])
def test_stock_status(stock, reorder, active, status):
    assert service.stock_status(stock, reorder, active) == status
