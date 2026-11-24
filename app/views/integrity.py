"""データ整合性チェック。"""

import streamlit as st
from common import db, page_header

from inventory import integrity

page_header("整合性チェック", "記録におかしなところがないかを 8 つの観点で確かめます。データは変更しません。")

if st.button("チェックする", type="primary", icon=":material/fact_check:") or "integrity" in st.session_state:
    with db() as s:
        results = integrity.run_checks(s)
    st.session_state["integrity"] = True
    bad = [r for r in results if not r.ok]
    if bad:
        st.error(f"{len(bad)} つのチェックで問題が見つかりました。下の内容を確認してください。", icon=":material/error:")
    else:
        st.success("すべてのチェックで問題はありませんでした。", icon=":material/verified:")
    for r in results:
        icon = ":material/check_circle:" if r.ok else ":material/error:"
        with st.expander(f"{'OK' if r.ok else '問題あり'}　{r.name}", icon=icon, expanded=not r.ok):
            st.caption(r.description)
            if r.ok:
                st.write("問題はありません。")
            else:
                # 商品名などは利用者が入れた文字なので、Markdown として解釈させずにそのまま出す
                st.text("\n".join(f"・{p}" for p in r.problems[:200]))
                if len(r.problems) > 200:
                    st.caption(f"ほか {len(r.problems) - 200} 件")
else:
    st.info("「チェックする」を押すと始めます。数秒で終わります。", icon=":material/info:")
