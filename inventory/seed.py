"""見本データ（架空の雑貨ショップ）を入れる。

今日から数えて約3か月分の入出庫を、毎日の販売と発注（発注点を下回ったら数日後に入庫）で作る。
登録はすべて service の関数を通すので、在庫がマイナスになる取引は入らない。
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from sqlalchemy.orm import Session

from . import service
from .errors import InventoryError
from .service import ProductInput

CATEGORIES = ["衣料", "雑貨", "文具", "食器"]

# (コード, 商品名, カテゴリ, 単位, 仕入単価, 発注点, 1日に売れる数の目安, 1回の発注数)
PRODUCTS = [
    ("TS-001", "Tシャツ ホワイト M", "衣料", "枚", 1200, 15, 2.2, 40),
    ("TS-002", "Tシャツ ブラック L", "衣料", "枚", 1200, 15, 1.8, 40),
    ("HD-110", "パーカー グレー L", "衣料", "枚", 3100, 6, 0.5, 15),
    ("CP-300", "キャップ ネイビー", "衣料", "個", 1400, 8, 0.9, 20),
    ("BG-101", "トートバッグ キャンバス", "雑貨", "個", 1500, 10, 1.1, 30),
    ("ST-205", "ステッカー 5枚セット", "雑貨", "セット", 180, 40, 4.5, 120),
    ("SK-400", "ソックス 3足組", "雑貨", "組", 600, 12, 1.4, 30),
    ("NB-500", "ノート A5 方眼", "文具", "冊", 350, 20, 2.6, 60),
    ("PN-510", "ボールペン 3色", "文具", "本", 160, 30, 3.0, 80),
    ("MG-010", "マグカップ 350ml", "食器", "個", 700, 10, 1.3, 30),
    ("TB-020", "タンブラー ステンレス", "食器", "個", 1300, 6, 0.6, 15),
    ("PL-030", "プレート 20cm", "食器", "枚", 900, 8, 0.4, 12),
]
SUPPLIERS = {"衣料": "みなと衣料", "雑貨": "サンプル雑貨", "文具": "ひかり文具", "食器": "やまと陶器"}
OUTLETS = ["ネットショップ", "ネットショップ", "ネットショップ", "店頭", "卸（カフェ）"]


def seed(s: Session, days: int = 90, today: date | None = None, rng_seed: int = 20261123) -> dict:
    """空の DB に見本データを入れる。入れた件数を返す。"""
    if not service.is_empty(s):
        raise InventoryError("データがもう入っているため、見本データは入れられません（空の DB のときだけ使えます）。")
    today = today or date.today()
    rng = random.Random(rng_seed)
    cats = {name: service.create_category(s, name) for name in CATEGORIES}
    start = today - timedelta(days=days)
    end = today - timedelta(days=1)
    stats = {"カテゴリ": len(cats), "商品": 0, "取引": 0}
    # 最後の方で発注を止めて「要発注」「在庫切れ」が出るようにする商品
    stop_reorder = {"HD-110": 25, "TB-020": 30}
    # 最後の日にまとめての注文が入り、発注点を下回る商品（「要発注」の例）
    bulk_to = {"PN-510": 18, "CP-300": 5, "SK-400": 9}

    for code, name, cat, unit, price, reorder, daily, lot in PRODUCTS:
        p = service.create_product(s, ProductInput(code=code, name=name, category_id=cats[cat].id, unit=unit,
                                                   unit_price=price, reorder_point=reorder))
        stats["商品"] += 1
        service.record_in(s, p.id, lot + reorder, start, SUPPLIERS[cat], "初期在庫", today=today)
        stock, arrival = lot + reorder, None
        d = start + timedelta(days=1)
        while d <= end:
            if arrival and d >= arrival:
                service.record_in(s, p.id, lot, d, SUPPLIERS[cat], "定期発注", today=today)
                stock += lot
                stats["取引"] += 1
                arrival = None
            # 週末は少し多く売れる
            mean = daily * (1.5 if d.weekday() >= 5 else 1.0)
            sold = sum(1 for _ in range(int(mean * 3)) if rng.random() < 1 / 3)
            sold = min(sold, stock)
            if sold:
                service.record_out(s, p.id, sold, d, rng.choice(OUTLETS), today=today)
                stock -= sold
                stats["取引"] += 1
            days_left = (end - d).days
            if stock <= reorder and arrival is None and days_left > stop_reorder.get(code, -1):
                arrival = d + timedelta(days=rng.randint(2, 4))
            d += timedelta(days=1)
        if code in bulk_to and stock > bulk_to[code]:
            service.record_out(s, p.id, stock - bulk_to[code], end, "卸（カフェ）", "まとめての注文", today=today)
            stats["取引"] += 1
        stats["取引"] += 1  # 初期在庫

    # 棚卸の調整（数え直したら 2 個少なかった）と、入力ミスの取消の例
    mug = service.find_product_by_code(s, "MG-010")
    check_day = today - timedelta(days=10)
    counted = max(service.balance(s, mug.id, as_of=check_day) - 2, 0)
    if counted != service.balance(s, mug.id, as_of=check_day):
        service.record_adjust(s, mug.id, counted, check_day, "棚卸：破損 2 個", today=today)
        stats["取引"] += 1
    note = service.find_product_by_code(s, "NB-500")
    wrong = service.record_in(s, note.id, 100, today - timedelta(days=5), SUPPLIERS["文具"], "数量を打ち間違えた", today=today)
    service.reverse_transaction(s, wrong.id, "数量の入力ミス（正しくは 10）")
    service.record_in(s, note.id, 10, today - timedelta(days=5), SUPPLIERS["文具"], "", today=today)
    stats["取引"] += 3
    return stats
