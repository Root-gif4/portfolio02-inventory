"""テーブルの定義（SQLAlchemy 2.x）。詳しくは docs/03_DB設計書.md。"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint, func)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# 取引の種類
IN = "IN"          # 入庫（在庫が増える）
OUT = "OUT"        # 出庫（在庫が減る）
ADJUST = "ADJUST"  # 棚卸の調整（実際の数に合わせて増減）
KINDS = (IN, OUT, ADJUST)
KIND_LABELS = {IN: "入庫", OUT: "出庫", ADJUST: "棚卸調整"}


class Base(DeclarativeBase):
    pass


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())

    products: Mapped[list["Product"]] = relationship(back_populates="category")

    __table_args__ = (CheckConstraint("length(trim(name)) > 0", name="ck_categories_name"),)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False)
    unit: Mapped[str] = mapped_column(String(10), nullable=False, default="個")
    unit_price: Mapped[int] = mapped_column(Integer, nullable=False, default=0)       # 仕入単価（円）。在庫金額の計算用
    reorder_point: Mapped[int] = mapped_column(Integer, nullable=False, default=0)    # 発注点：在庫がこの数以下で「要発注」
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp(),
                                                 onupdate=func.current_timestamp())

    category: Mapped[Category] = relationship(back_populates="products")
    transactions: Mapped[list["StockTransaction"]] = relationship(back_populates="product")

    __table_args__ = (
        CheckConstraint("unit_price >= 0", name="ck_products_unit_price"),
        CheckConstraint("reorder_point >= 0", name="ck_products_reorder_point"),
        CheckConstraint("length(trim(code)) > 0 AND length(trim(name)) > 0", name="ck_products_code_name"),
    )


class StockTransaction(Base):
    """入出庫の取引。確定した取引は書き換え・削除せず、取消は「逆向きの取引」を追加して行う。

    delta：在庫の増減（入庫 +quantity、出庫 −quantity、棚卸調整は ± の差分）。
    取消の取引は reversal_of に元の取引の id を持ち、delta は元の −1 倍。
    在庫数 = その商品の delta の合計。
    """

    __tablename__ = "stock_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)   # 入力した数（いつも 1 以上）
    delta: Mapped[int] = mapped_column(Integer, nullable=False)      # 在庫の増減
    txn_date: Mapped[date] = mapped_column(Date, nullable=False)
    partner: Mapped[str] = mapped_column(String(100), nullable=False, default="")  # 仕入先・出荷先など
    memo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reversal_of: Mapped[int | None] = mapped_column(ForeignKey("stock_transactions.id", ondelete="RESTRICT"),
                                                    nullable=True, unique=True)  # 同じ取引は1回しか取り消せない
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())

    product: Mapped[Product] = relationship(back_populates="transactions")

    __table_args__ = (
        CheckConstraint("kind IN ('IN','OUT','ADJUST')", name="ck_txn_kind"),
        CheckConstraint("quantity > 0", name="ck_txn_quantity"),
        CheckConstraint("delta <> 0", name="ck_txn_delta"),
        # 取消でない取引は、種類と delta の向きが合っていること
        CheckConstraint(
            "reversal_of IS NOT NULL OR (kind='IN' AND delta=quantity) OR (kind='OUT' AND delta=-quantity) "
            "OR (kind='ADJUST' AND abs(delta)=quantity)", name="ck_txn_direction"),
        Index("ix_txn_product_date", "product_id", "txn_date", "id"),
        Index("ix_txn_date", "txn_date"),
        UniqueConstraint("reversal_of", name="uq_txn_reversal_of"),
    )
