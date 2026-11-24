"""CSV の取り込み・書き出し。

- 書き出しは Excel で開ける BOM 付き UTF-8。先頭が = + - @ の値は数式として動かないよう ' を付ける
- 取り込みは「全部正しいときだけ保存」。1 行でもエラーがあれば何も保存せず、行番号つきのエラー一覧を返す
- 確認（dry_run）では、実際に登録してみてから必ず取り消す（在庫が足りるかまで確かめられる）
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy.orm import Session

from . import service
from .errors import InventoryError
from .models import IN, KIND_LABELS, OUT

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 10_000
_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")

PRODUCT_COLUMNS = ["商品コード", "商品名", "カテゴリ", "単位", "仕入単価", "発注点", "メモ"]
PRODUCT_REQUIRED = ["商品コード", "商品名", "カテゴリ"]
TXN_COLUMNS = ["取引日", "種類", "商品コード", "数量", "取引先", "メモ"]
TXN_REQUIRED = ["取引日", "種類", "商品コード", "数量"]
KIND_FROM_LABEL = {"入庫": IN, "出庫": OUT, "IN": IN, "OUT": OUT}


# ------------------------------------------------------------------ 書き出し

def sanitize_cell(value):
    """Excel で開いたときに数式として動かないようにする（CSV インジェクション対策）。"""
    if not isinstance(value, str) or not value:
        return value
    if value[0] in ("=", "+", "-", "@", "\t", "\r") and not _NUMBER.match(value):
        return "'" + value
    return value


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    safe = df.copy()
    for col in safe.columns:
        # pandas 3 では文字の列が object ではなく str 型になるので、「数値でない列」をすべて対象にする
        if not pd.api.types.is_numeric_dtype(safe[col]):
            safe[col] = safe[col].map(sanitize_cell)
    return safe.to_csv(index=False, lineterminator="\r\n").encode("utf-8-sig")


def export_products(s: Session) -> bytes:
    rows = [{"商品コード": p.code, "商品名": p.name, "カテゴリ": p.category.name, "単位": p.unit,
             "仕入単価": p.unit_price, "発注点": p.reorder_point, "メモ": p.note,
             "使用中": "はい" if p.active else "いいえ"} for p in service.list_products(s)]
    return to_csv_bytes(pd.DataFrame(rows, columns=[*PRODUCT_COLUMNS, "使用中"]))


def export_stock(s: Session) -> bytes:
    df = service.stock_table(s, include_inactive=True)
    df = df.drop(columns=["id"]).assign(使用中=df["使用中"].map({True: "はい", False: "いいえ"}))
    return to_csv_bytes(df)


def export_transactions(df: pd.DataFrame) -> bytes:
    cols = ["No", "取引日", "種類", "状態", "商品コード", "商品名", "カテゴリ", "数量", "増減", "単位", "取引先", "メモ",
            "取消元", "登録日時"]
    out = df[cols].copy()
    out["取消元"] = out["取消元"].map(lambda v: "" if pd.isna(v) else int(v))
    return to_csv_bytes(out)


# ------------------------------------------------------------------ 取り込み

@dataclass
class ImportResult:
    rows: int = 0
    created: int = 0
    updated: int = 0
    errors: list[tuple[int, str]] = field(default_factory=list)   # (CSV の行番号, 内容)
    saved: bool = False
    encoding: str = ""

    @property
    def ok(self) -> bool:
        return not self.errors

    def errors_df(self) -> pd.DataFrame:
        return pd.DataFrame(self.errors, columns=["行番号", "内容"])


def read_csv_bytes(data: bytes, required: list[str]) -> tuple[list[tuple[int, dict]], str]:
    """(行番号, {列名: 値}) の一覧と文字コード。読めないときは InventoryError。"""
    if len(data) > MAX_BYTES:
        raise InventoryError(f"ファイルが大きすぎます（{len(data) / 1024 / 1024:.1f}MB）。5MB までにしてください。")
    if b"\x00" in data:
        raise InventoryError("CSV ではないファイルのようです（バイナリが含まれています）。")
    for enc, label in (("utf-8-sig", "UTF-8"), ("cp932", "Shift_JIS")):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise InventoryError("文字コードが分かりません。UTF-8 か Shift_JIS の CSV で保存し直してください。")
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = [h.strip() for h in next(reader)]
    except StopIteration:
        raise InventoryError("ファイルが空です。") from None
    missing = [c for c in required if c not in header]
    if missing:
        raise InventoryError("必要な列がありません：" + "、".join(missing) + "（1 行目の見出しを確認してください）")
    if len(set(header)) != len(header):
        raise InventoryError("同じ名前の見出しが 2 つ以上あります。")
    rows = []
    for line_no, values in enumerate(reader, start=2):
        if not any(v.strip() for v in values):
            continue
        if len(rows) >= MAX_ROWS:
            raise InventoryError(f"行が多すぎます。{MAX_ROWS:,} 行までにしてください。")
        values = values + [""] * (len(header) - len(values))
        rows.append((line_no, dict(zip(header, values[:len(header)]))))
    return rows, label


def import_products(s: Session, data: bytes, dry_run: bool = True, update_existing: bool = True,
                    create_categories: bool = True) -> ImportResult:
    rows, enc = read_csv_bytes(data, PRODUCT_REQUIRED)
    result = ImportResult(rows=len(rows), encoding=enc)
    seen: dict[str, int] = {}
    savepoint = s.begin_nested()
    try:
        for line_no, row in rows:
            try:
                code = service.clean_code(row.get("商品コード"))
                if code in seen:
                    raise InventoryError(f"商品コード {code} が {seen[code]} 行目と重なっています。")
                seen[code] = line_no
                cat_name = service.clean_text(row.get("カテゴリ"), "カテゴリ", 50, required=True)
                cat = next((c for c in service.list_categories(s) if c.name.lower() == cat_name.lower()), None)
                if cat is None:
                    if not create_categories:
                        raise InventoryError(f"カテゴリ「{cat_name}」がありません。")
                    cat = service.create_category(s, cat_name)
                data_in = service.ProductInput(
                    code=code, name=row.get("商品名", ""), category_id=cat.id, unit=row.get("単位") or "個",
                    unit_price=row.get("仕入単価") or 0, reorder_point=row.get("発注点") or 0, note=row.get("メモ", ""))
                existing = service.find_product_by_code(s, code)
                if existing:
                    if not update_existing:
                        raise InventoryError(f"商品コード {code} はもう登録されています。")
                    service.update_product(s, existing.id, data_in)
                    result.updated += 1
                else:
                    service.create_product(s, data_in)
                    result.created += 1
            except InventoryError as exc:
                result.errors.append((line_no, str(exc)))
        if dry_run or result.errors:
            savepoint.rollback()
        else:
            savepoint.commit()
            result.saved = True
    except Exception:
        if savepoint.is_active:
            savepoint.rollback()
        raise
    return result


def import_transactions(s: Session, data: bytes, dry_run: bool = True, today=None) -> ImportResult:
    """入庫・出庫をまとめて登録する（CSV の行の順に登録し、在庫が足りるかも確かめる）。"""
    rows, enc = read_csv_bytes(data, TXN_REQUIRED)
    result = ImportResult(rows=len(rows), encoding=enc)
    savepoint = s.begin_nested()
    try:
        for line_no, row in rows:
            try:
                kind_label = service.clean_text(row.get("種類"), "種類", 10, required=True)
                kind = KIND_FROM_LABEL.get(kind_label.upper() if kind_label.isascii() else kind_label)
                if kind is None:
                    raise InventoryError(f"種類は「入庫」か「出庫」にしてください（「{kind_label}」は使えません）。"
                                         "棚卸調整は画面から登録します。")
                code = service.clean_code(row.get("商品コード"))
                product = service.find_product_by_code(s, code)
                if product is None:
                    raise InventoryError(f"商品コード {code} の商品が登録されていません。")
                fn = service.record_in if kind == IN else service.record_out
                fn(s, product.id, row.get("数量"), row.get("取引日"), row.get("取引先", ""), row.get("メモ", ""),
                   today=today)
                result.created += 1
            except InventoryError as exc:
                result.errors.append((line_no, str(exc)))
        if dry_run or result.errors:
            savepoint.rollback()
        else:
            savepoint.commit()
            result.saved = True
    except Exception:
        if savepoint.is_active:
            savepoint.rollback()
        raise
    return result


def template_products() -> bytes:
    return to_csv_bytes(pd.DataFrame([["TS-101", "Tシャツ ネイビー M", "衣料", "枚", 1200, 10, ""]],
                                     columns=PRODUCT_COLUMNS))


def template_transactions() -> bytes:
    return to_csv_bytes(pd.DataFrame([["2026-11-20", KIND_LABELS[IN], "TS-101", 20, "〇〇商事", ""],
                                      ["2026-11-21", KIND_LABELS[OUT], "TS-101", 3, "ネットショップ", ""]],
                                     columns=TXN_COLUMNS))
