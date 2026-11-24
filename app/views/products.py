"""商品マスタ：追加・変更・使用停止。"""

import streamlit as st
from common import STATUS_ICON, db, page_header, run_action

from inventory import service
from inventory.service import ProductInput

page_header("商品", "商品の登録と変更です。商品は削除せず、使わなくなったら「使用停止」にします（履歴を残すため）。")

with db() as s:
    cats = {c.id: c.name for c in service.list_categories(s, include_inactive=False)}
    stock = service.stock_table(s, include_inactive=True)

if not cats:
    st.info("使用中のカテゴリがありません。先に「カテゴリ」で登録してください。", icon=":material/info:")
    st.page_link("views/categories.py", label="カテゴリを登録する", icon=":material/arrow_forward:")
    st.stop()


def product_form(prefix: str, p=None) -> ProductInput | None:
    """商品の入力欄。p を渡すとその値を初期値にする。"""
    c1, c2 = st.columns([1, 2])
    code = c1.text_input("商品コード（必須）", value=p.code if p else "", max_chars=20, key=f"{prefix}_code",
                         placeholder="例：TS-001", help="半角の英数字・ハイフン。取引のある商品は変えられません。")
    name = c2.text_input("商品名（必須）", value=p.name if p else "", max_chars=100, key=f"{prefix}_name",
                         placeholder="例：Tシャツ ホワイト M")
    c3, c4, c5, c6 = st.columns(4)
    cat_ids = list(cats)
    idx = cat_ids.index(p.category_id) if p and p.category_id in cat_ids else 0
    category_id = c3.selectbox("カテゴリ", cat_ids, index=idx, format_func=cats.get, key=f"{prefix}_cat")
    unit = c4.text_input("単位", value=p.unit if p else "個", max_chars=10, key=f"{prefix}_unit")
    price = c5.number_input("仕入単価（円）", min_value=0, max_value=service.MAX_PRICE, step=10,
                            value=p.unit_price if p else 0, key=f"{prefix}_price")
    reorder = c6.number_input("発注点", min_value=0, max_value=service.MAX_QUANTITY, step=1,
                              value=p.reorder_point if p else 0, key=f"{prefix}_reorder",
                              help="在庫がこの数以下になると「要発注」と表示します")
    note = st.text_area("メモ", value=p.note if p else "", max_chars=500, height=68, key=f"{prefix}_note")
    return ProductInput(code=code, name=name, category_id=category_id, unit=unit, unit_price=int(price),
                        reorder_point=int(reorder), note=note)


tab_list, tab_add, tab_edit = st.tabs([":material/list: 一覧", ":material/add: 追加する", ":material/edit: 変更・使用停止"])

with tab_list:
    show_inactive = st.toggle("使用停止の商品も表示する", value=True)
    view = stock if show_inactive else stock[stock["使用中"]]
    view = view.assign(状態=view["状態"].map(STATUS_ICON))[["状態", "商品コード", "商品名", "カテゴリ", "単位", "仕入単価",
                                                          "発注点", "在庫数"]]
    st.dataframe(view, hide_index=True, width="stretch",
                 column_config={"仕入単価": st.column_config.NumberColumn(format="yen")})
    st.caption(f"{len(view):,} 件")

with tab_add:
    with st.form("add_product", clear_on_submit=False, border=True):
        data = product_form("add")
        if st.form_submit_button("この内容で追加する", type="primary", icon=":material/add:"):
            run_action(lambda s: service.create_product(s, data), lambda p: f"商品「{p.name}」（{p.code}）を追加しました")

with tab_edit:
    with db() as s:
        products = service.list_products(s)
    if not products:
        st.caption("商品がまだありません。")
    else:
        labels = {p.id: f"{p.code}　{p.name}" + ("（使用停止）" if not p.active else "") for p in products}
        pid = st.selectbox("変更する商品", list(labels), format_func=labels.get, index=None,
                           placeholder="コードか商品名を入力して探せます")
        if pid is not None:
            p = next(x for x in products if x.id == pid)
            with st.form(f"edit_{pid}", border=True):
                data = product_form(f"edit{pid}", p)
                if st.form_submit_button("変更を保存する", type="primary", icon=":material/save:"):
                    run_action(lambda s: service.update_product(s, pid, data), lambda x: f"「{x.name}」を変更しました")
            with st.container(border=True):
                if p.active:
                    st.markdown("**使用停止にする**　在庫が 0 のときだけできます。停止中は入出庫を登録できません。")
                    if st.button("使用停止にする", icon=":material/block:"):
                        run_action(lambda s: service.set_product_active(s, pid, False), f"「{p.name}」を使用停止にしました")
                else:
                    st.markdown("**使用を再開する**")
                    if st.button("使用を再開する", icon=":material/replay:"):
                        run_action(lambda s: service.set_product_active(s, pid, True), f"「{p.name}」の使用を再開しました")
