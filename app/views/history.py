"""取引履歴の検索と、取引の取消。"""

from datetime import date, timedelta

import streamlit as st
from common import KIND_ICON, db, page_header, run_action

from inventory import csvio, service
from inventory.models import KIND_LABELS

page_header("取引履歴・取消", "条件で絞り込んで探せます。間違えた取引は、下の「取引を取り消す」で取り消します（記録は消えずに残ります）。")

with db() as s:
    cats = {c.id: c.name for c in service.list_categories(s)}
    prods = {p.id: f"{p.code}　{p.name}" for p in service.list_products(s)}

with st.container(border=True):
    c1, c2, c3 = st.columns([3, 2, 2])
    period = c1.date_input("期間", value=(date.today() - timedelta(days=30), date.today()), max_value=date.today(),
                           format="YYYY-MM-DD", help="始めと終わりの日を選びます")
    cat_id = c2.selectbox("カテゴリ", [None, *cats], format_func=lambda k: "すべて" if k is None else cats[k])
    prod_id = c3.selectbox("商品", [None, *prods], format_func=lambda k: "すべて" if k is None else prods[k])
    c4, c5, c6 = st.columns([3, 3, 2])
    kinds = c4.multiselect("種類", list(KIND_LABELS), format_func=KIND_LABELS.get, placeholder="すべて")
    keyword = c5.text_input("キーワード", placeholder="商品・取引先・メモの一部")
    hide_rev = c6.toggle("取消したものを隠す", value=False)

date_from, date_to = (period + (None,))[:2] if isinstance(period, tuple) else (period, None)
f = service.TxnFilter(date_from=date_from, date_to=date_to or date_from, product_id=prod_id, category_id=cat_id,
                      kinds=tuple(kinds), keyword=keyword, hide_reversed=hide_rev)
with db() as s:
    df = service.search_transactions(s, f)

ins = int(df.loc[(df["種類コード"] == "IN"), "増減"].sum()) if len(df) else 0
outs = -int(df.loc[(df["種類コード"] == "OUT"), "増減"].sum()) if len(df) else 0
m1, m2, m3 = st.columns(3)
m1.metric("見つかった取引", f"{len(df):,} 件", border=True)
m2.metric("入庫数（取消を差し引き）", f"{ins:,}", border=True)
m3.metric("出庫数（取消を差し引き）", f"{outs:,}", border=True)

view = df.assign(種類=df["種類"].map(KIND_ICON))[["No", "取引日", "種類", "商品コード", "商品名", "増減", "単位", "取引先",
                                                  "メモ", "状態"]]
st.dataframe(view, hide_index=True, width="stretch", height=min(38 + 35 * max(len(view), 1), 560),
             column_config={"取引日": st.column_config.DateColumn(format="YYYY-MM-DD"),
                            "増減": st.column_config.NumberColumn(format="%+d"),
                            "状態": st.column_config.TextColumn(help="取消＝取り消すための取引／取消済み＝取り消された取引")})
if len(df) >= f.limit:
    st.warning(f"件数が多いため、新しい順に {f.limit:,} 件だけ表示しています。期間を狭めてください。")
st.download_button("表示している取引を CSV で保存", csvio.export_transactions(df),
                   file_name=f"取引履歴_{date.today():%Y%m%d}.csv", mime="text/csv", icon=":material/download:")

# ---- 取消
st.divider()
st.subheader(":material/undo: 取引を取り消す")
st.caption("取り消すと、同じ日付で増減が逆の「取消」の取引が追加され、在庫が元に戻ります。1 つの取引は 1 回だけ取り消せます。")
candidates = df[df["状態"] == ""]
if candidates.empty:
    st.caption("上の一覧に、取り消せる取引がありません。")
else:
    options = {int(r.No): f"No.{r.No}　{r.取引日:%Y-%m-%d}　{r.種類}　{r.商品名}　{r.増減:+,}{r.単位}"
               for r in candidates.itertuples()}
    with st.container(border=True):
        target = st.selectbox("取り消す取引（上の一覧から選びます）", list(options), format_func=options.get, index=None,
                              key="rev_target",
                              placeholder="No. か商品名を入力して探せます")
        reason = st.text_input("取消の理由", max_chars=500, placeholder="例：数量の入力ミス")
        sure = st.checkbox("この取引を取り消します（取り消した記録も残ります）", disabled=target is None, key="rev_sure")
        if st.button("取り消す", type="primary", icon=":material/undo:", disabled=not (target and sure)):
            run_action(lambda s: service.reverse_transaction(s, target, reason),
                       lambda t: f"No.{target} を取り消しました（取消の取引 No.{t.id}）")
