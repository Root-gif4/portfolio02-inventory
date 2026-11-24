"""CSV の取り込み（商品・入出庫）と書き出し。取り込みは「確認 → 取り込む」の 2 段階。"""

import hashlib
from datetime import date

import streamlit as st
from common import db, logger, page_header, run_action

from inventory import csvio, service
from inventory.errors import InventoryError

page_header("CSV 取り込み・書き出し",
            "ほかの表から商品や入出庫をまとめて登録できます。1 行でも誤りがあると何も登録しません（直してからもう一度）。")

tab_in, tab_out = st.tabs([":material/upload: 取り込む", ":material/download: 書き出す"])

KINDS = {
    "products": ("商品", csvio.import_products, csvio.template_products, csvio.PRODUCT_COLUMNS, csvio.PRODUCT_REQUIRED),
    "transactions": ("入庫・出庫", csvio.import_transactions, csvio.template_transactions, csvio.TXN_COLUMNS,
                     csvio.TXN_REQUIRED),
}

with tab_in:
    kind = st.radio("取り込むもの", list(KINDS), format_func=lambda k: KINDS[k][0], horizontal=True)
    label, importer, template, columns, required = KINDS[kind]

    with st.expander(f"{label}の CSV の形（見出し）", expanded=False):
        st.write("1 行目に次の見出しを入れます。**太字** は必須です。文字コードは UTF-8 か Shift_JIS。")
        st.markdown("、".join(f"**{c}**" if c in required else c for c in columns))
        if kind == "products":
            st.caption("同じ商品コードがすでにあれば、内容を上書きします。ないカテゴリは新しく作ります。")
        else:
            st.caption("種類は「入庫」か「出庫」。商品コードは登録済みのもの。上の行から順に登録し、在庫が足りるかも確かめます。")
        st.download_button("ひな形をダウンロード", template(), file_name=f"ひな形_{label}.csv", mime="text/csv",
                           icon=":material/description:")

    file = st.file_uploader(f"{label}の CSV ファイル", type=["csv"], key=f"upload_{kind}",
                            help="5MB・10,000 行まで")
    if file is not None:
        data = file.getvalue()
        digest = hashlib.sha256(data).hexdigest()
        check_key = f"checked_{kind}"
        if st.button("内容を確認する", icon=":material/fact_check:"):
            try:
                with db() as s:
                    result = importer(s, data, dry_run=True)
                st.session_state[check_key] = (digest, result)
            except InventoryError as exc:
                st.session_state.pop(check_key, None)
                st.error(str(exc), icon=":material/error:")
            except Exception:
                logger().exception("CSV の確認で想定外のエラー")
                st.error("ファイルを読み込めませんでした。CSV の形を確認してください。", icon=":material/error:")

        checked = st.session_state.get(check_key)
        if checked and checked[0] == digest:
            result = checked[1]
            c1, c2, c3 = st.columns(3)
            c1.metric("行数", f"{result.rows:,}", border=True)
            c2.metric("新しく登録" if kind == "products" else "登録する取引", f"{result.created:,}", border=True)
            if kind == "products":
                c3.metric("上書き", f"{result.updated:,}", border=True)
            else:
                c3.metric("文字コード", result.encoding, border=True)
            if result.ok:
                st.success("誤りはありません。「取り込む」を押すと登録します。", icon=":material/check_circle:")
                if st.button(f"{result.rows:,} 行を取り込む", type="primary", icon=":material/upload:"):
                    def action(s):
                        r = importer(s, data, dry_run=False)
                        if not r.ok:  # 確認のあとでデータが変わった場合
                            raise InventoryError("確認のあとでデータが変わったため、取り込めませんでした。もう一度確認してください。")
                        return r
                    st.session_state.pop(check_key, None)
                    run_action(action, lambda r: f"{label}を取り込みました（{r.created + r.updated:,} 件）")
            else:
                st.error(f"{len(result.errors):,} 行に誤りがあります。CSV を直してから、もう一度選んでください（何も登録していません）。",
                         icon=":material/error:")
                st.dataframe(result.errors_df(), hide_index=True, width="stretch")

with tab_out:
    st.write("Excel で開ける形（BOM 付き UTF-8）で保存します。")
    with db() as s:
        products_csv = csvio.export_products(s)
        stock_csv = csvio.export_stock(s)
        all_txn = csvio.export_transactions(service.search_transactions(s, service.TxnFilter(limit=1_000_000)))
    today = f"{date.today():%Y%m%d}"
    c1, c2, c3 = st.columns(3)
    with c1, st.container(border=True):
        st.markdown("##### 商品マスタ")
        st.caption("そのまま「商品」の取り込みに使えます")
        st.download_button("保存する", products_csv, file_name=f"商品_{today}.csv", mime="text/csv", key="dl_p",
                           icon=":material/download:")
    with c2, st.container(border=True):
        st.markdown("##### 在庫一覧")
        st.caption("今日の在庫数・在庫金額・状態")
        st.download_button("保存する", stock_csv, file_name=f"在庫一覧_{today}.csv", mime="text/csv", key="dl_s",
                           icon=":material/download:")
    with c3, st.container(border=True):
        st.markdown("##### 取引履歴（すべて）")
        st.caption("取消の取引も含みます")
        st.download_button("保存する", all_txn, file_name=f"取引履歴_{today}.csv", mime="text/csv", key="dl_t",
                           icon=":material/download:")
