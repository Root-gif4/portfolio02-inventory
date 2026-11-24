"""入庫・出庫・棚卸調整の登録。"""

from datetime import date

import streamlit as st
from common import STATUS_ICON, db, page_header, product_label, run_action

from inventory import service
from inventory.models import KIND_LABELS

page_header("入庫・出庫の登録", "商品を選んで数量と日付を入れ、「登録する」を押します。在庫数は自動で増減します。")

# 登録できたら、取引先とメモの欄を空に戻す（ウィジェットを作る前に消す）
if st.session_state.pop("_entry_clear", False):
    for key in ("entry_partner", "entry_memo"):
        st.session_state.pop(key, None)

with db() as s:
    products = service.list_products(s, include_inactive=False)
    stock = service.stock_table(s).set_index("id")

if not products:
    st.info("使用中の商品がありません。先に「商品」で登録してください。", icon=":material/info:")
    st.page_link("views/products.py", label="商品を登録する", icon=":material/arrow_forward:")
    st.stop()

labels = {p.id: product_label(p, int(stock.loc[p.id, "在庫数"])) for p in products}
by_id = {p.id: p for p in products}

mode = st.segmented_control("登録するもの", ["入庫", "出庫", "棚卸調整"], default="入庫", key="entry_mode",
                            help="入庫＝仕入れなどで増える／出庫＝販売などで減る／棚卸調整＝数えた数に合わせる")
mode = mode or "入庫"
explain = {
    "入庫": "仕入れや返品の受け入れなどで、在庫が **増える** ときに使います。",
    "出庫": "販売・出荷・社内での使用などで、在庫が **減る** ときに使います。在庫より多くは出庫できません。",
    "棚卸調整": "実際に数えた数を入れると、記録との **差** を調整として登録します（破損・紛失など）。",
}
st.info(explain[mode], icon=":material/lightbulb:")

left, right = st.columns([3, 2], gap="large")
with left, st.container(border=True):
    pid = st.selectbox("商品", options=list(labels), format_func=labels.get, key="entry_product",
                       placeholder="コードか商品名を入力して探せます", index=None)
    c1, c2 = st.columns(2)
    if mode == "棚卸調整":
        qty = c1.number_input("数えた数", min_value=0, max_value=service.MAX_QUANTITY, step=1, value=0, key="entry_count")
    else:
        qty = c1.number_input("数量", min_value=1, max_value=service.MAX_QUANTITY, step=1, value=1, key="entry_qty")
    txn_date = c2.date_input("日付", value=date.today(), max_value=date.today(), format="YYYY-MM-DD", key="entry_date",
                             help="未来の日付は入れられません。過去の日付で出庫するときは、その後の在庫も足りるか確かめます。")
    partner = ""
    if mode != "棚卸調整":
        partner = st.text_input("仕入先" if mode == "入庫" else "出荷先・使った人", max_chars=100, key="entry_partner",
                                placeholder="例：みなと衣料／ネットショップ（任意）")
    memo = st.text_input("メモ", max_chars=500, key="entry_memo", placeholder="任意")

    # 登録前に、登録後の在庫を計算しておく（マイナスになるときはボタンを押せなくする）
    preview = None
    if pid is not None:
        with db() as s:
            now_at_date = service.balance(s, pid, as_of=txn_date)
            now = service.balance(s, pid)
        delta = {"入庫": int(qty), "出庫": -int(qty)}.get(mode, int(qty) - now_at_date)
        preview = {"now": now, "now_at_date": now_at_date, "delta": delta, "after": now + delta}
    blocked = preview is None or preview["after"] < 0 or (mode == "棚卸調整" and preview["delta"] == 0)
    submitted = st.button(f"{mode}を登録する", type="primary", icon=":material/check:", width="stretch",
                          disabled=blocked)

with right:
    st.markdown("##### 登録すると")
    if preview is None:
        st.caption("左で商品を選ぶと、登録前と登録後の在庫数がここに出ます。")
    else:
        p = by_id[pid]
        now, delta, after = preview["now"], preview["delta"], preview["after"]
        with st.container(border=True):
            c1, c2 = st.columns(2)
            c1.metric("今の在庫", f"{now:,} {p.unit}")
            c2.metric("登録後の在庫", f"{after:,} {p.unit}", delta=f"{delta:+,}" if delta else "±0", delta_color="normal")
            status = service.stock_status(after, p.reorder_point)
            st.write(f"状態：{STATUS_ICON[status]}　（発注点 {p.reorder_point:,}{p.unit}）")
            if txn_date != date.today():
                st.caption(f"{txn_date.isoformat()} 時点の在庫は {preview['now_at_date']:,}{p.unit} です。")
            if after < 0:
                st.error("在庫がマイナスになるため登録できません。数量を見直してください。", icon=":material/block:")
            elif mode == "棚卸調整" and delta == 0:
                st.caption("記録と同じ数なので、調整は要りません。")
if submitted and pid is not None:
    def action(s):
        if mode == "入庫":
            return service.record_in(s, pid, int(qty), txn_date, partner, memo)
        if mode == "出庫":
            return service.record_out(s, pid, int(qty), txn_date, partner, memo)
        return service.record_adjust(s, pid, int(qty), txn_date, memo)

    def done(t):
        st.session_state["_entry_clear"] = True
        p = by_id[pid]
        return (f"{KIND_LABELS[t.kind]}を登録しました（No.{t.id}）：{p.name} {t.delta:+,}{p.unit}")

    run_action(action, done)
