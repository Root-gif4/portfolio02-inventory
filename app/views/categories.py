"""カテゴリの追加・名前の変更・使用停止。"""

import pandas as pd
import streamlit as st
from common import db, page_header, run_action

from inventory import service

page_header("カテゴリ", "商品の分類です（例：衣料・文具）。使用中の商品があるカテゴリは使用停止にできません。")

with db() as s:
    cats = service.list_categories(s)
    stock = service.stock_table(s, include_inactive=True)

counts = stock.groupby("カテゴリ").agg(商品数=("id", "count"), 在庫数=("在庫数", "sum"))
rows = [{"カテゴリ": c.name, "状態": "🟢 使用中" if c.active else "⚪ 使用停止",
         "商品数": int(counts["商品数"].get(c.name, 0)), "在庫数": int(counts["在庫数"].get(c.name, 0))} for c in cats]

left, right = st.columns([3, 2], gap="large")
with left:
    st.dataframe(pd.DataFrame(rows, columns=["カテゴリ", "状態", "商品数", "在庫数"]), hide_index=True, width="stretch")

with right:
    with st.container(border=True):
        st.markdown("##### :material/add: 追加する")
        with st.form("add_category", clear_on_submit=True, border=False):
            name = st.text_input("カテゴリ名", max_chars=50, placeholder="例：衣料")
            if st.form_submit_button("追加する", type="primary"):
                run_action(lambda s: service.create_category(s, name), lambda c: f"カテゴリ「{c.name}」を追加しました")

    if cats:
        with st.container(border=True):
            st.markdown("##### :material/edit: 名前の変更・使用停止")
            labels = {c.id: c.name + ("（使用停止）" if not c.active else "") for c in cats}
            cid = st.selectbox("カテゴリ", list(labels), format_func=labels.get)
            target = next(c for c in cats if c.id == cid)
            new_name = st.text_input("新しい名前", value=target.name, max_chars=50, key=f"rename_{cid}")
            b1, b2 = st.columns(2)
            if b1.button("名前を変える", disabled=new_name.strip() == target.name):
                run_action(lambda s: service.rename_category(s, cid, new_name), lambda c: f"名前を「{c.name}」に変えました")
            if target.active:
                if b2.button("使用停止にする", icon=":material/block:"):
                    run_action(lambda s: service.set_category_active(s, cid, False), f"「{target.name}」を使用停止にしました")
            elif b2.button("使用を再開する", icon=":material/replay:"):
                run_action(lambda s: service.set_category_active(s, cid, True), f"「{target.name}」の使用を再開しました")
