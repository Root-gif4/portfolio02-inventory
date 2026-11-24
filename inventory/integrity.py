"""データ整合性チェック。DB を直接書き換えられた場合なども見つけられるよう、画面の入力チェックとは別に確かめる。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.orm import Session, aliased

from .models import ADJUST, IN, OUT, Category, Product, StockTransaction


@dataclass
class CheckResult:
    name: str
    description: str
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def run_checks(s: Session, today: date | None = None) -> list[CheckResult]:
    today = today or date.today()
    return [
        _sqlite_integrity(s),
        _foreign_keys(s),
        _direction(s),
        _reversals(s),
        _never_negative(s),
        _future_dates(s, today),
        _inactive_with_stock(s),
        _inactive_category(s),
    ]


def summary_df(results: list[CheckResult]) -> pd.DataFrame:
    return pd.DataFrame([{"チェック": r.name, "結果": "OK" if r.ok else "問題あり", "件数": len(r.problems),
                          "内容": r.description} for r in results])


def _sqlite_integrity(s: Session) -> CheckResult:
    r = CheckResult("DB ファイルの壊れ", "SQLite の integrity_check で、DB ファイルが壊れていないか")
    rows = [row[0] for row in s.execute(text("PRAGMA integrity_check")).all()]
    if rows != ["ok"]:
        r.problems = rows[:50]
    return r


def _foreign_keys(s: Session) -> CheckResult:
    r = CheckResult("つながりの切れ", "取引の商品・商品のカテゴリ・取消元が、存在しないものを指していないか")
    for table, rowid, parent, _ in s.execute(text("PRAGMA foreign_key_check")).all():
        r.problems.append(f"{table} の {rowid} 行目が、存在しない {parent} を指しています")
    return r


def _direction(s: Session) -> CheckResult:
    r = CheckResult("取引の向き", "入庫は増える・出庫は減る・数量は 1 以上、など種類と増減が合っているか")
    rows = s.execute(select(StockTransaction.id, StockTransaction.kind, StockTransaction.quantity,
                            StockTransaction.delta, StockTransaction.reversal_of)).all()
    for tid, kind, qty, delta, rev in rows:
        if qty is None or qty <= 0 or delta == 0:
            r.problems.append(f"No.{tid}：数量 {qty}・増減 {delta} が正しくありません")
            continue
        if rev is not None:
            continue  # 取消は _reversals で確かめる
        expected = {IN: qty, OUT: -qty}.get(kind)
        if kind == ADJUST:
            if abs(delta) != qty:
                r.problems.append(f"No.{tid}：棚卸調整の数量 {qty} と増減 {delta} が合いません")
        elif expected is None:
            r.problems.append(f"No.{tid}：種類「{kind}」は使えません")
        elif delta != expected:
            r.problems.append(f"No.{tid}：{kind} なのに増減が {delta} です（{expected} のはず）")
    return r


def _reversals(s: Session) -> CheckResult:
    r = CheckResult("取消の対応", "取消の取引が、元の取引と同じ商品・種類・日付で、増減がちょうど逆か")
    orig = aliased(StockTransaction)
    rows = s.execute(select(StockTransaction, orig)
                     .join(orig, StockTransaction.reversal_of == orig.id)).all()
    for rev, o in rows:
        if o.reversal_of is not None:
            r.problems.append(f"No.{rev.id}：取消の取引（No.{o.id}）をさらに取り消しています")
        if (rev.product_id, rev.kind, rev.txn_date) != (o.product_id, o.kind, o.txn_date):
            r.problems.append(f"No.{rev.id}：元の取引 No.{o.id} と商品・種類・日付が違います")
        if rev.delta != -o.delta or rev.quantity != o.quantity:
            r.problems.append(f"No.{rev.id}：元の取引 No.{o.id} の増減 {o.delta} の逆になっていません（{rev.delta}）")
    return r


def _never_negative(s: Session) -> CheckResult:
    r = CheckResult("在庫のマイナス", "どの日の終わりにも、在庫がマイナスになっていないか")
    rows = s.execute(select(StockTransaction.product_id, StockTransaction.txn_date, StockTransaction.delta)
                     .order_by(StockTransaction.product_id, StockTransaction.txn_date, StockTransaction.id)).all()
    names = dict(s.execute(select(Product.id, Product.name)).all())
    running: dict[int, int] = {}
    reported: set[int] = set()
    for i, (pid, d, delta) in enumerate(rows):
        running[pid] = running.get(pid, 0) + delta
        last_of_day = i + 1 == len(rows) or rows[i + 1][0] != pid or rows[i + 1][1] != d
        if last_of_day and running[pid] < 0 and pid not in reported:
            reported.add(pid)
            r.problems.append(f"「{names.get(pid, pid)}」：{d.isoformat()} の在庫が {running[pid]} になっています")
    return r


def _future_dates(s: Session, today: date) -> CheckResult:
    r = CheckResult("未来の日付", f"今日（{today.isoformat()}）より後の日付の取引がないか")
    for tid, d in s.execute(select(StockTransaction.id, StockTransaction.txn_date)
                            .where(StockTransaction.txn_date > today)).all():
        r.problems.append(f"No.{tid}：{d.isoformat()}")
    return r


def _inactive_with_stock(s: Session) -> CheckResult:
    r = CheckResult("使用停止の商品の在庫", "使用停止にした商品に在庫が残っていないか")
    from .service import balance
    for p in s.scalars(select(Product).where(Product.active.is_(False))):
        stock = balance(s, p.id)
        if stock != 0:
            r.problems.append(f"「{p.name}」（{p.code}）：在庫 {stock}")
    return r


def _inactive_category(s: Session) -> CheckResult:
    r = CheckResult("使用停止のカテゴリ", "使用停止のカテゴリに、使用中の商品が入っていないか")
    rows = s.execute(select(Product.code, Product.name, Category.name)
                     .join(Category, Product.category_id == Category.id)
                     .where(Product.active.is_(True), Category.active.is_(False))).all()
    for code, name, cat in rows:
        r.problems.append(f"「{name}」（{code}）がカテゴリ「{cat}」に入っています")
    return r
