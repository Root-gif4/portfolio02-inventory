"""ダッシュボード：在庫の今の様子をひと目で見る。"""

import altair as alt
import streamlit as st
from common import STATUS_ICON, db, num, page_header, run_action, yen

from inventory import seed, service

page_header("ダッシュボード", "在庫の今の様子です。気になる商品は「入庫・出庫の登録」で入庫してください。")

with db() as s:
    empty = service.is_empty(s)

if empty:
    st.info("まだデータがありません。まずは見本データで試すか、「マスタ」から商品を登録してください。",
            icon=":material/info:")
    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        st.markdown("#### :material/science: 見本データで試す")
        st.write("架空の雑貨ショップ（12 商品・約 3 か月分の入出庫）を入れます。")
        if st.button("見本データを入れる", type="primary", icon=":material/download:"):
            run_action(lambda s: seed.seed(s), lambda r: f"見本データを入れました（商品 {r['商品']}・取引 {r['取引']} 件）")
    with c2, st.container(border=True):
        st.markdown("#### :material/edit: 自分のデータで始める")
        st.write("カテゴリ → 商品 の順に登録し、入庫を記録すると在庫が増えます。")
        st.page_link("views/categories.py", label="カテゴリを登録する", icon=":material/arrow_forward:")
    st.stop()

with db() as s:
    nums = service.dashboard_numbers(s)
    al = service.alerts(s)
    stock = service.stock_table(s)
    monthly = service.monthly_summary(s)
    recent = service.search_transactions(s, service.TxnFilter(limit=8))

# ---- 数字のカード
cols = st.columns(5)
cards = [
    ("商品数", num(nums["商品数"]), "使用中の商品", None),
    ("在庫金額", yen(nums["在庫金額"]), "在庫数 × 仕入単価", None),
    ("在庫切れ", f"{nums['在庫切れ']} 件", "在庫が 0 の商品", "inverse" if nums["在庫切れ"] else "off"),
    ("要発注", f"{nums['要発注']} 件", "発注点以下の商品", "inverse" if nums["要発注"] else "off"),
    ("今月の入庫 / 出庫", f"{num(nums['今月の入庫数'])} / {num(nums['今月の出庫数'])}", "数量の合計", None),
]
for col, (label, value, help_text, _) in zip(cols, cards):
    col.metric(label, value, help=help_text, border=True)

# ---- 要対応の商品
st.subheader(":material/warning: 要対応の商品")
if al.empty:
    st.success("在庫切れ・要発注の商品はありません。", icon=":material/check_circle:")
else:
    view = al.assign(状態=al["状態"].map(STATUS_ICON))[["状態", "商品コード", "商品名", "カテゴリ", "在庫数", "発注点",
                                                         "不足数", "単位", "最終取引日"]]
    st.dataframe(view, hide_index=True, width="stretch",
                 column_config={"在庫数": st.column_config.NumberColumn(format="%d"),
                                "不足数": st.column_config.NumberColumn("発注点までの不足", format="%d"),
                                "最終取引日": st.column_config.DateColumn(format="YYYY-MM-DD")})
    st.page_link("views/entry.py", label="入庫を登録する", icon=":material/arrow_forward:")

# ---- グラフ
left, right = st.columns([3, 2])
with left:
    st.subheader(":material/bar_chart: 月別の入庫・出庫")
    if monthly.empty:
        st.caption("取引がまだありません。")
    else:
        long = monthly.melt(id_vars="月", value_vars=["入庫数", "出庫数"], var_name="区分", value_name="数量")
        chart = (alt.Chart(long).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
                 .encode(x=alt.X("月:N", title=None, axis=alt.Axis(labelAngle=0)),
                         xOffset="区分:N",
                         y=alt.Y("数量:Q", title="数量", axis=alt.Axis(format=",.0f")),
                         color=alt.Color("区分:N", scale=alt.Scale(domain=["入庫数", "出庫数"],
                                                                 range=["#2e9e6b", "#e8833a"]),
                                         legend=alt.Legend(orient="top", title=None)),
                         tooltip=["月", "区分", alt.Tooltip("数量:Q", format=",")])
                 .properties(height=320))
        st.altair_chart(chart, width="stretch")
with right:
    st.subheader(":material/pie_chart: カテゴリ別の在庫金額")
    by_cat = stock.groupby("カテゴリ", as_index=False)["在庫金額"].sum().sort_values("在庫金額", ascending=False)
    if by_cat["在庫金額"].sum() == 0:
        st.caption("在庫がありません。")
    else:
        chart = (alt.Chart(by_cat).mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4, color="#4c78d8")
                 .encode(y=alt.Y("カテゴリ:N", sort="-x", title=None),
                         x=alt.X("在庫金額:Q", title="在庫金額（円）", axis=alt.Axis(format=",.0f", tickCount=4)),
                         tooltip=["カテゴリ", alt.Tooltip("在庫金額:Q", format=",")])
                 .properties(height=320))
        text = chart.mark_text(align="left", dx=4, color="#8b93a7").encode(text=alt.Text("在庫金額:Q", format=",.0f"))
        st.altair_chart(chart + text, width="stretch")

# ---- 最近の取引
st.subheader(":material/history: 最近の取引")
if recent.empty:
    st.caption("取引がまだありません。")
else:
    view = recent[["No", "取引日", "種類", "商品名", "増減", "単位", "取引先", "状態"]]
    st.dataframe(view, hide_index=True, width="stretch",
                 column_config={"取引日": st.column_config.DateColumn(format="YYYY-MM-DD"),
                                "増減": st.column_config.NumberColumn(format="%+d")})
    st.page_link("views/history.py", label="取引履歴をすべて見る", icon=":material/arrow_forward:")
