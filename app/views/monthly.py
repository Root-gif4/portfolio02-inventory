"""月別の入出庫集計。"""

from datetime import date

import altair as alt
import streamlit as st
from common import db, page_header, yen

from inventory import csvio, service

page_header("月別集計", "月ごとの入庫数・出庫数です。取り消した取引は差し引いて数えます。")

with db() as s:
    cats = {c.id: c.name for c in service.list_categories(s)}
    prods = {p.id: f"{p.code}　{p.name}" for p in service.list_products(s)}

c1, c2, c3, c4 = st.columns(4)
start_year = c1.number_input("いつから（年）", min_value=2000, max_value=date.today().year, value=date.today().year - 1
                             if date.today().month < 12 else date.today().year, step=1)
start_month = c2.selectbox("（月）", list(range(1, 13)), index=(date.today().month % 12), format_func=lambda m: f"{m} 月")
cat_id = c3.selectbox("カテゴリ", [None, *cats], format_func=lambda k: "すべて" if k is None else cats[k])
prod_id = c4.selectbox("商品", [None, *prods], format_func=lambda k: "すべて" if k is None else prods[k])

with db() as s:
    df = service.monthly_summary(s, date_from=date(int(start_year), int(start_month), 1),
                                 category_id=cat_id, product_id=prod_id)

if df.empty:
    st.info("この条件の取引はありません。", icon=":material/info:")
    st.stop()

m1, m2, m3, m4 = st.columns(4)
m1.metric("入庫数の合計", f"{int(df['入庫数'].sum()):,}", border=True)
m2.metric("出庫数の合計", f"{int(df['出庫数'].sum()):,}", border=True)
m3.metric("入庫金額の合計", yen(df["入庫金額"].sum()), border=True, help="数量 × 今の仕入単価")
m4.metric("出庫金額の合計", yen(df["出庫金額"].sum()), border=True, help="数量 × 今の仕入単価（原価）")

long = df.melt(id_vars="月", value_vars=["入庫数", "出庫数"], var_name="区分", value_name="数量")
bars = (alt.Chart(long).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
        .encode(x=alt.X("月:N", title=None, axis=alt.Axis(labelAngle=0)), xOffset="区分:N",
                y=alt.Y("数量:Q", title="数量", axis=alt.Axis(format=",.0f")),
                color=alt.Color("区分:N", scale=alt.Scale(domain=["入庫数", "出庫数"], range=["#2e9e6b", "#e8833a"]),
                                legend=alt.Legend(orient="top", title=None)),
                tooltip=["月", "区分", alt.Tooltip("数量:Q", format=",")]))
labels = bars.mark_text(dy=-6, fontSize=11, color="#8b93a7").encode(text=alt.Text("数量:Q", format=",.0f"))
st.altair_chart((bars + labels).properties(height=340), width="stretch")

st.dataframe(df, hide_index=True, width="stretch",
             column_config={"差引": st.column_config.NumberColumn("差引（在庫の増減）", format="%+d"),
                            "入庫金額": st.column_config.NumberColumn(format="yen"),
                            "出庫金額": st.column_config.NumberColumn(format="yen")})
st.download_button("この集計を CSV で保存", csvio.to_csv_bytes(df), file_name=f"月別集計_{date.today():%Y%m%d}.csv",
                   mime="text/csv", icon=":material/download:")
