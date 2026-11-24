"""在庫一覧：商品ごとの在庫数・状態。過去の日付の在庫も見られる。"""

from datetime import date

import streamlit as st
from common import STATUS_ICON, db, page_header, yen

from inventory import csvio, service

page_header("在庫一覧", "在庫数は入出庫の記録から計算しています。日付を変えると、その日の終わりの在庫が分かります。")

with db() as s:
    cats = [c.name for c in service.list_categories(s)]

f1, f2, f3, f4 = st.columns([2, 2, 3, 2])
cat = f1.selectbox("カテゴリ", ["すべて", *cats])
status = f2.multiselect("状態", list(STATUS_ICON.values())[:3], placeholder="すべて")
keyword = f3.text_input("商品コード・商品名で探す", placeholder="例：TS-001、マグ")
as_of = f4.date_input("この日の在庫", value=date.today(), max_value=date.today(), format="YYYY-MM-DD")
show_inactive = st.toggle("使用停止の商品も表示する", value=False)

with db() as s:
    df = service.stock_table(s, as_of=as_of, include_inactive=show_inactive)
# 状態は「その日の在庫」で付け直す
df["状態"] = [service.stock_status(a, b, c) for a, b, c in zip(df["在庫数"], df["発注点"], df["使用中"])]
df["状態表示"] = df["状態"].map(STATUS_ICON)
if cat != "すべて":
    df = df[df["カテゴリ"] == cat]
if status:
    df = df[df["状態表示"].isin(status)]
if keyword.strip():
    k = keyword.strip().lower()
    df = df[df["商品コード"].str.lower().str.contains(k, regex=False) | df["商品名"].str.lower().str.contains(k, regex=False)]

c1, c2, c3 = st.columns(3)
c1.metric("表示している商品", f"{len(df):,} 件", border=True)
c2.metric("在庫数の合計", f"{int(df['在庫数'].sum()):,}", border=True)
c3.metric("在庫金額の合計", yen(df["在庫金額"].sum()), border=True)

view = df[["状態表示", "商品コード", "商品名", "カテゴリ", "在庫数", "単位", "発注点", "仕入単価", "在庫金額", "最終取引日"]]
max_stock = int(max(df["在庫数"].max() if len(df) else 0, 1))
st.dataframe(view, hide_index=True, width="stretch", height=min(38 + 35 * max(len(view), 1), 640),
             column_config={
                 "状態表示": st.column_config.TextColumn("状態"),
                 "在庫数": st.column_config.ProgressColumn("在庫数", format="%d", min_value=0, max_value=max_stock),
                 "仕入単価": st.column_config.NumberColumn(format="yen"),
                 "在庫金額": st.column_config.NumberColumn(format="yen"),
                 "最終取引日": st.column_config.DateColumn(format="YYYY-MM-DD"),
             })
st.caption("状態：🔴 在庫切れ＝0 以下／🟡 要発注＝発注点以下／🟢 適正。発注点は「商品」で変えられます。")

data = csvio.to_csv_bytes(view.rename(columns={"状態表示": "状態"}).assign(基準日=as_of.isoformat()))
st.download_button("表示している在庫一覧を CSV で保存", data, file_name=f"在庫一覧_{as_of:%Y%m%d}.csv", mime="text/csv",
                   icon=":material/download:")
