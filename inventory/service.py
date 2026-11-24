"""業務の処理（DB の読み書きはここに集める）。

大事な決まり：
- 在庫数は保存しない。その商品の取引の delta を足して求める（stock = Σdelta）
- 在庫を減らす取引（出庫・棚卸で減らす・入庫の取消）は、その日付以降のどの時点でも
  在庫がマイナスにならないときだけ受け付ける（過去の日付で入れた場合も確かめる）
- 確定した取引は書き換え・削除しない。取消は元の取引と同じ日付で逆向きの取引を足す（1回だけ）
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, aliased

from .errors import InventoryError, NotFoundError
from .models import ADJUST, IN, KIND_LABELS, KINDS, OUT, Category, Product, StockTransaction

MIN_DATE = date(2000, 1, 1)
MAX_QUANTITY = 1_000_000
MAX_PRICE = 100_000_000
CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,19}$")

STATUS_OUT = "在庫切れ"
STATUS_LOW = "要発注"
STATUS_OK = "適正"
STATUS_INACTIVE = "使用停止"


# ------------------------------------------------------------------ 入力の整え・確認

def clean_text(value, field: str, max_len: int, required: bool = False) -> str:
    text = "" if value is None else unicodedata.normalize("NFKC", str(value)).strip()
    if required and not text:
        raise InventoryError(f"{field}を入力してください。")
    if len(text) > max_len:
        raise InventoryError(f"{field}は{max_len}文字以内にしてください（今は{len(text)}文字）。")
    if any(unicodedata.category(ch) == "Cc" and ch not in "\n\t" for ch in text):
        raise InventoryError(f"{field}に使えない文字（制御文字）が入っています。")
    return text


def clean_code(value) -> str:
    code = clean_text(value, "商品コード", 20, required=True).upper().replace("ー", "-").replace("－", "-")
    if not CODE_RE.match(code):
        raise InventoryError("商品コードは半角の英数字・ハイフン・アンダーバーで、20文字以内にしてください（例：TS-001）。")
    return code


def clean_int(value, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise InventoryError(f"{field}は整数で入力してください。")
    if isinstance(value, float):
        if not value.is_integer():
            raise InventoryError(f"{field}は整数で入力してください。")
        value = int(value)
    if isinstance(value, str):
        text = unicodedata.normalize("NFKC", value).strip().replace(",", "").replace("円", "")
        if not re.fullmatch(r"-?\d+", text):
            raise InventoryError(f"{field}は整数で入力してください（「{value}」は読めません）。")
        value = int(text)
    if not isinstance(value, int):
        raise InventoryError(f"{field}は整数で入力してください。")
    if value < minimum or value > maximum:
        raise InventoryError(f"{field}は{minimum:,}〜{maximum:,}の範囲で入力してください。")
    return value


def clean_date(value, today: date | None = None) -> date:
    today = today or date.today()
    if isinstance(value, str):
        text = unicodedata.normalize("NFKC", value).strip().replace("/", "-")
        try:
            value = date.fromisoformat(text) if len(text) == 10 else date(*map(int, text.split("-")))
        except (ValueError, TypeError):
            raise InventoryError(f"日付は 2026-11-23 の形で入力してください（「{value}」は読めません）。") from None
    if isinstance(value, datetime):  # pandas の Timestamp も datetime の仲間
        value = value.date()
    if not isinstance(value, date):
        raise InventoryError("日付を入力してください。")
    if value < MIN_DATE:
        raise InventoryError(f"日付は {MIN_DATE.isoformat()} 以降にしてください。")
    if value > today:
        raise InventoryError(f"未来の日付（{value.isoformat()}）は入力できません。今日（{today.isoformat()}）までの日付にしてください。")
    return value


# ------------------------------------------------------------------ カテゴリ

def list_categories(s: Session, include_inactive: bool = True) -> list[Category]:
    q = select(Category).order_by(Category.name)
    if not include_inactive:
        q = q.where(Category.active.is_(True))
    return list(s.scalars(q))


def get_category(s: Session, category_id: int) -> Category:
    cat = s.get(Category, category_id)
    if cat is None:
        raise NotFoundError("カテゴリが見つかりません（削除されたか、番号が違います）。")
    return cat


def _category_name_taken(s: Session, name: str, exclude_id: int | None = None) -> bool:
    q = select(Category.id).where(func.lower(Category.name) == name.lower())
    if exclude_id is not None:
        q = q.where(Category.id != exclude_id)
    return s.scalar(q) is not None


def create_category(s: Session, name) -> Category:
    name = clean_text(name, "カテゴリ名", 50, required=True)
    if _category_name_taken(s, name):
        raise InventoryError(f"カテゴリ「{name}」はもうあります。")
    cat = Category(name=name, active=True)
    s.add(cat)
    s.flush()
    return cat


def rename_category(s: Session, category_id: int, name) -> Category:
    cat = get_category(s, category_id)
    name = clean_text(name, "カテゴリ名", 50, required=True)
    if _category_name_taken(s, name, exclude_id=cat.id):
        raise InventoryError(f"カテゴリ「{name}」はもうあります。")
    cat.name = name
    s.flush()
    return cat


def set_category_active(s: Session, category_id: int, active: bool) -> Category:
    cat = get_category(s, category_id)
    if not active:
        used = s.scalar(select(func.count()).select_from(Product)
                        .where(Product.category_id == cat.id, Product.active.is_(True)))
        if used:
            raise InventoryError(f"カテゴリ「{cat.name}」には使用中の商品が {used} 件あるため、使用停止にできません。"
                                 "先に商品のカテゴリを変えるか、商品を使用停止にしてください。")
    cat.active = active
    s.flush()
    return cat


# ------------------------------------------------------------------ 商品

def list_products(s: Session, include_inactive: bool = True) -> list[Product]:
    q = select(Product).order_by(Product.code)
    if not include_inactive:
        q = q.where(Product.active.is_(True))
    return list(s.scalars(q))


def get_product(s: Session, product_id: int) -> Product:
    p = s.get(Product, product_id)
    if p is None:
        raise NotFoundError("商品が見つかりません（番号が違います）。")
    return p


def find_product_by_code(s: Session, code: str) -> Product | None:
    return s.scalar(select(Product).where(Product.code == code))


@dataclass
class ProductInput:
    code: str
    name: str
    category_id: int
    unit: str = "個"
    unit_price: int = 0
    reorder_point: int = 0
    note: str = ""


def _clean_product(s: Session, data: ProductInput) -> dict:
    cat = get_category(s, int(data.category_id))
    if not cat.active:
        raise InventoryError(f"カテゴリ「{cat.name}」は使用停止中です。別のカテゴリを選んでください。")
    return {
        "code": clean_code(data.code),
        "name": clean_text(data.name, "商品名", 100, required=True),
        "category_id": cat.id,
        "unit": clean_text(data.unit or "個", "単位", 10, required=True),
        "unit_price": clean_int(data.unit_price, "仕入単価", 0, MAX_PRICE),
        "reorder_point": clean_int(data.reorder_point, "発注点", 0, MAX_QUANTITY),
        "note": clean_text(data.note, "メモ", 500),
    }


def create_product(s: Session, data: ProductInput) -> Product:
    values = _clean_product(s, data)
    if find_product_by_code(s, values["code"]):
        raise InventoryError(f"商品コード「{values['code']}」はもう使われています。")
    p = Product(**values, active=True)
    s.add(p)
    s.flush()
    return p


def update_product(s: Session, product_id: int, data: ProductInput) -> Product:
    p = get_product(s, product_id)
    values = _clean_product(s, data)
    if values["code"] != p.code:
        if has_transactions(s, p.id):
            raise InventoryError("取引のある商品は商品コードを変えられません（履歴との対応が分からなくなるため）。")
        if find_product_by_code(s, values["code"]):
            raise InventoryError(f"商品コード「{values['code']}」はもう使われています。")
    for key, value in values.items():
        setattr(p, key, value)
    s.flush()
    return p


def set_product_active(s: Session, product_id: int, active: bool) -> Product:
    p = get_product(s, product_id)
    if not active:
        stock = balance(s, p.id)
        if stock != 0:
            raise InventoryError(f"「{p.name}」は在庫が {stock:,}{p.unit} 残っているため使用停止にできません。"
                                 "出庫か棚卸調整で 0 にしてから使用停止にしてください。")
    elif not p.category.active:
        raise InventoryError(f"カテゴリ「{p.category.name}」が使用停止中です。先にカテゴリを使用中に戻してください。")
    p.active = active
    s.flush()
    return p


def has_transactions(s: Session, product_id: int) -> bool:
    return s.scalar(select(StockTransaction.id).where(StockTransaction.product_id == product_id).limit(1)) is not None


# ------------------------------------------------------------------ 在庫数

def balance(s: Session, product_id: int, as_of: date | None = None) -> int:
    """在庫数（as_of を渡すとその日の終わりの在庫数）。"""
    q = select(func.coalesce(func.sum(StockTransaction.delta), 0)).where(StockTransaction.product_id == product_id)
    if as_of is not None:
        q = q.where(StockTransaction.txn_date <= as_of)
    return int(s.scalar(q))


def _first_negative(s: Session, product_id: int, new_delta: int, new_date: date) -> tuple[date, int] | None:
    """新しい取引（new_date の日の最後に入る）を足したとき、在庫がマイナスになる最初の日と数。"""
    rows = s.execute(select(StockTransaction.txn_date, StockTransaction.delta)
                     .where(StockTransaction.product_id == product_id)
                     .order_by(StockTransaction.txn_date, StockTransaction.id)).all()
    events = [(d, delta) for d, delta in rows]
    # 同じ日の既存の取引のあとに入れる（並びは日付 → 登録順）
    pos = next((i for i, (d, _) in enumerate(events) if d > new_date), len(events))
    events.insert(pos, (new_date, new_delta))
    running = 0
    for i, (d, delta) in enumerate(events):
        running += delta
        # 同じ日の取引がまだ続くときは、その日の終わりで判定する
        last_of_day = i + 1 == len(events) or events[i + 1][0] != d
        if last_of_day and running < 0 and d >= new_date:
            return d, running
    return None


def _ensure_never_negative(s: Session, product: Product, delta: int, txn_date: date) -> None:
    if delta >= 0:
        return
    hit = _first_negative(s, product.id, delta, txn_date)
    if hit:
        d, amount = hit
        now = balance(s, product.id, as_of=txn_date)
        if d == txn_date:
            raise InventoryError(f"「{product.name}」の在庫が足りません。{txn_date.isoformat()} の在庫は {now:,}{product.unit} で、"
                                 f"{-delta:,}{product.unit} 減らすと {amount:,}{product.unit} になります。")
        raise InventoryError(f"「{product.name}」は {txn_date.isoformat()} の時点では足りますが、そのあとの出庫があるため "
                             f"{d.isoformat()} に在庫が {amount:,}{product.unit} になってしまいます。"
                             "日付を見直すか、先に入庫を登録してください。")


# ------------------------------------------------------------------ 取引

def _active_product(s: Session, product_id: int) -> Product:
    p = get_product(s, int(product_id))
    if not p.active:
        raise InventoryError(f"「{p.name}」は使用停止中のため、入出庫を登録できません。")
    return p


def _add(s: Session, product: Product, kind: str, quantity: int, delta: int, txn_date: date,
         partner: str = "", memo: str = "", reversal_of: int | None = None) -> StockTransaction:
    _ensure_never_negative(s, product, delta, txn_date)
    t = StockTransaction(product_id=product.id, kind=kind, quantity=quantity, delta=delta, txn_date=txn_date,
                         partner=partner, memo=memo, reversal_of=reversal_of)
    s.add(t)
    s.flush()
    return t


def record_in(s: Session, product_id: int, quantity, txn_date, partner="", memo="",
              today: date | None = None) -> StockTransaction:
    p = _active_product(s, product_id)
    qty = clean_int(quantity, "数量", 1, MAX_QUANTITY)
    d = clean_date(txn_date, today)
    return _add(s, p, IN, qty, qty, d, clean_text(partner, "仕入先", 100), clean_text(memo, "メモ", 500))


def record_out(s: Session, product_id: int, quantity, txn_date, partner="", memo="",
               today: date | None = None) -> StockTransaction:
    p = _active_product(s, product_id)
    qty = clean_int(quantity, "数量", 1, MAX_QUANTITY)
    d = clean_date(txn_date, today)
    return _add(s, p, OUT, qty, -qty, d, clean_text(partner, "出荷先", 100), clean_text(memo, "メモ", 500))


def record_adjust(s: Session, product_id: int, counted, txn_date, memo="",
                  today: date | None = None) -> StockTransaction:
    """棚卸：数えた数（counted）に合わせて、その日の在庫との差を記録する。"""
    p = _active_product(s, product_id)
    counted = clean_int(counted, "数えた数", 0, MAX_QUANTITY)
    d = clean_date(txn_date, today)
    memo = clean_text(memo, "メモ", 500)
    diff = counted - balance(s, p.id, as_of=d)
    if diff == 0:
        raise InventoryError(f"{d.isoformat()} の在庫はもう {counted:,}{p.unit} なので、調整は要りません。")
    return _add(s, p, ADJUST, abs(diff), diff, d, "", memo or f"棚卸（数えた数 {counted:,}）")


def get_transaction(s: Session, txn_id: int) -> StockTransaction:
    t = s.get(StockTransaction, int(txn_id))
    if t is None:
        raise NotFoundError("取引が見つかりません（番号が違います）。")
    return t


def reverse_transaction(s: Session, txn_id: int, memo="") -> StockTransaction:
    """取消：元の取引と同じ日付・同じ種類で、増減が逆の取引を足す。"""
    t = get_transaction(s, txn_id)
    if t.reversal_of is not None:
        raise InventoryError("取消の取引は取り消せません。もう一度登録し直してください。")
    if s.scalar(select(StockTransaction.id).where(StockTransaction.reversal_of == t.id)) is not None:
        raise InventoryError(f"取引 No.{t.id} はもう取り消されています。")
    memo = clean_text(memo, "取消の理由", 500)
    return _add(s, t.product, t.kind, t.quantity, -t.delta, t.txn_date, t.partner,
                memo or f"No.{t.id} の取消", reversal_of=t.id)


# ------------------------------------------------------------------ 一覧・集計

def stock_table(s: Session, as_of: date | None = None, include_inactive: bool = False) -> pd.DataFrame:
    """商品ごとの在庫数・在庫金額・状態。"""
    sums = select(StockTransaction.product_id.label("pid"),
                  func.coalesce(func.sum(StockTransaction.delta), 0).label("stock"),
                  func.max(StockTransaction.txn_date).label("last_date"))
    if as_of is not None:
        sums = sums.where(StockTransaction.txn_date <= as_of)
    sums = sums.group_by(StockTransaction.product_id).subquery()
    q = (select(Product.id, Product.code, Product.name, Category.name, Product.unit, Product.unit_price,
                Product.reorder_point, func.coalesce(sums.c.stock, 0), sums.c.last_date, Product.active)
         .join(Category, Product.category_id == Category.id)
         .outerjoin(sums, sums.c.pid == Product.id)
         .order_by(Product.code))
    if not include_inactive:
        q = q.where(Product.active.is_(True))
    cols = ["id", "商品コード", "商品名", "カテゴリ", "単位", "仕入単価", "発注点", "在庫数", "最終取引日", "使用中"]
    df = pd.DataFrame(s.execute(q).all(), columns=cols)
    if df.empty:
        df["在庫金額"] = pd.Series(dtype="int64")
        df["状態"] = pd.Series(dtype="object")
        return df
    df["在庫数"] = df["在庫数"].astype("int64")
    df["在庫金額"] = (df["在庫数"] * df["仕入単価"]).astype("int64")
    df["状態"] = [stock_status(st, rp, act) for st, rp, act in zip(df["在庫数"], df["発注点"], df["使用中"])]
    return df


def stock_status(stock: int, reorder_point: int, active: bool = True) -> str:
    if not active:
        return STATUS_INACTIVE
    if stock <= 0:
        return STATUS_OUT
    if stock <= reorder_point:
        return STATUS_LOW
    return STATUS_OK


def alerts(s: Session) -> pd.DataFrame:
    """在庫切れ・要発注の商品（在庫切れを先に、そのあと発注点との差が大きい順）。"""
    df = stock_table(s)
    df = df[df["状態"].isin([STATUS_OUT, STATUS_LOW])].copy()
    df["不足数"] = (df["発注点"] - df["在庫数"]).clip(lower=0)
    df["_order"] = df["状態"].map({STATUS_OUT: 0, STATUS_LOW: 1})
    return df.sort_values(["_order", "不足数"], ascending=[True, False]).drop(columns="_order").reset_index(drop=True)


@dataclass
class TxnFilter:
    date_from: date | None = None
    date_to: date | None = None
    product_id: int | None = None
    category_id: int | None = None
    kinds: tuple[str, ...] = ()
    keyword: str = ""
    hide_reversed: bool = False   # 取り消した取引と取消の取引を隠す
    limit: int = 5000


def search_transactions(s: Session, f: TxnFilter | None = None) -> pd.DataFrame:
    f = f or TxnFilter()
    rev = aliased(StockTransaction)
    reversed_by = (select(rev.id).where(rev.reversal_of == StockTransaction.id).correlate(StockTransaction)
                   .scalar_subquery())
    q = (select(StockTransaction.id, StockTransaction.txn_date, StockTransaction.kind, Product.code, Product.name,
                Category.name, StockTransaction.quantity, StockTransaction.delta, Product.unit,
                StockTransaction.partner, StockTransaction.memo, StockTransaction.reversal_of,
                reversed_by.label("reversed_by"), StockTransaction.created_at)
         .join(Product, StockTransaction.product_id == Product.id)
         .join(Category, Product.category_id == Category.id)
         .order_by(StockTransaction.txn_date.desc(), StockTransaction.id.desc()))
    if f.date_from:
        q = q.where(StockTransaction.txn_date >= f.date_from)
    if f.date_to:
        q = q.where(StockTransaction.txn_date <= f.date_to)
    if f.product_id:
        q = q.where(StockTransaction.product_id == f.product_id)
    if f.category_id:
        q = q.where(Product.category_id == f.category_id)
    if f.kinds:
        q = q.where(StockTransaction.kind.in_([k for k in f.kinds if k in KINDS]))
    keyword = unicodedata.normalize("NFKC", f.keyword or "").strip()
    if keyword:
        like = "%" + keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        q = q.where((Product.code.ilike(like, escape="\\")) | (Product.name.ilike(like, escape="\\"))
                    | (StockTransaction.partner.ilike(like, escape="\\")) | (StockTransaction.memo.ilike(like, escape="\\")))
    if f.hide_reversed:
        q = q.where(StockTransaction.reversal_of.is_(None), reversed_by.is_(None))
    q = q.limit(f.limit)
    cols = ["No", "取引日", "種類コード", "商品コード", "商品名", "カテゴリ", "数量", "増減", "単位", "取引先", "メモ",
            "取消元", "取消した取引", "登録日時"]
    df = pd.DataFrame(s.execute(q).all(), columns=cols)
    df["種類"] = df["種類コード"].map(KIND_LABELS)
    df["状態"] = ["取消" if pd.notna(a) else ("取消済み" if pd.notna(b) else "")
                  for a, b in zip(df["取消元"], df["取消した取引"])]
    return df


def monthly_summary(s: Session, date_from: date | None = None, date_to: date | None = None,
                    category_id: int | None = None, product_id: int | None = None) -> pd.DataFrame:
    """月ごとの入庫数・出庫数・棚卸調整・差引（取消は元の月で差し引く）。"""
    month = func.strftime("%Y-%m", StockTransaction.txn_date).label("月")
    q = (select(month,
                func.coalesce(func.sum(case((StockTransaction.kind == IN, StockTransaction.delta), else_=0)), 0),
                func.coalesce(func.sum(case((StockTransaction.kind == OUT, -StockTransaction.delta), else_=0)), 0),
                func.coalesce(func.sum(case((StockTransaction.kind == ADJUST, StockTransaction.delta), else_=0)), 0),
                func.coalesce(func.sum(case((StockTransaction.kind == IN, StockTransaction.delta * Product.unit_price),
                                            else_=0)), 0),
                func.coalesce(func.sum(case((StockTransaction.kind == OUT, -StockTransaction.delta * Product.unit_price),
                                            else_=0)), 0))
         .join(Product, StockTransaction.product_id == Product.id)
         .group_by(month).order_by(month))
    if date_from:
        q = q.where(StockTransaction.txn_date >= date_from)
    if date_to:
        q = q.where(StockTransaction.txn_date <= date_to)
    if category_id:
        q = q.where(Product.category_id == category_id)
    if product_id:
        q = q.where(StockTransaction.product_id == product_id)
    df = pd.DataFrame(s.execute(q).all(), columns=["月", "入庫数", "出庫数", "棚卸調整", "入庫金額", "出庫金額"])
    for c in df.columns[1:]:
        df[c] = df[c].astype("int64")
    df.insert(4, "差引", df["入庫数"] - df["出庫数"] + df["棚卸調整"])
    return df


def dashboard_numbers(s: Session) -> dict:
    stock = stock_table(s)
    month_start = date.today().replace(day=1)
    this_month = monthly_summary(s, date_from=month_start)
    return {
        "商品数": int(len(stock)),
        "在庫数の合計": int(stock["在庫数"].sum()) if not stock.empty else 0,
        "在庫金額": int(stock["在庫金額"].sum()) if not stock.empty else 0,
        "在庫切れ": int((stock["状態"] == STATUS_OUT).sum()) if not stock.empty else 0,
        "要発注": int((stock["状態"] == STATUS_LOW).sum()) if not stock.empty else 0,
        "今月の入庫数": int(this_month["入庫数"].sum()) if not this_month.empty else 0,
        "今月の出庫数": int(this_month["出庫数"].sum()) if not this_month.empty else 0,
        "取引件数": int(s.scalar(select(func.count()).select_from(StockTransaction))),
    }


def is_empty(s: Session) -> bool:
    return s.scalar(select(Product.id).limit(1)) is None and s.scalar(select(Category.id).limit(1)) is None
