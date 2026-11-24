"""在庫管理システムの画面（入口）。起動：start.bat または
    .venv\\Scripts\\python.exe -m streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import db  # noqa: E402

from inventory import __version__  # noqa: E402
from inventory.service import alerts  # noqa: E402

st.set_page_config(page_title="在庫管理システム", page_icon=":material/inventory_2:", layout="wide")

st.logo(str(Path(__file__).resolve().parent / "logo.svg"), size="large")

VIEWS = Path(__file__).resolve().parent / "views"
pages = {
    "ホーム": [
        st.Page(VIEWS / "dashboard.py", title="ダッシュボード", icon=":material/dashboard:", default=True),
    ],
    "毎日の作業": [
        st.Page(VIEWS / "entry.py", title="入庫・出庫の登録", icon=":material/swap_vert:"),
        st.Page(VIEWS / "stock.py", title="在庫一覧", icon=":material/inventory_2:"),
    ],
    "記録を見る": [
        st.Page(VIEWS / "history.py", title="取引履歴・取消", icon=":material/history:"),
        st.Page(VIEWS / "monthly.py", title="月別集計", icon=":material/bar_chart:"),
    ],
    "マスタ": [
        st.Page(VIEWS / "products.py", title="商品", icon=":material/sell:"),
        st.Page(VIEWS / "categories.py", title="カテゴリ", icon=":material/category:"),
    ],
    "データ管理": [
        st.Page(VIEWS / "csv_io.py", title="CSV 取り込み・書き出し", icon=":material/upload_file:"),
        st.Page(VIEWS / "integrity.py", title="整合性チェック", icon=":material/fact_check:"),
        st.Page(VIEWS / "backup.py", title="バックアップ", icon=":material/backup:"),
    ],
}

with st.sidebar:
    try:
        with db() as s:
            al = alerts(s)
        n_out = int((al["状態"] == "在庫切れ").sum())
        n_low = len(al) - n_out
        if len(al):
            st.warning(f"要対応の商品が **{len(al)} 件**（在庫切れ {n_out}・要発注 {n_low}）", icon=":material/warning:")
        else:
            st.success("在庫の足りない商品はありません", icon=":material/check_circle:")
    except Exception:  # サイドバーの表示で止めない（各ページでエラーを出す）
        pass

nav = st.navigation(pages)
with st.sidebar:
    st.divider()
    st.caption(f"v{__version__}　画面の明るさ：右上の「︙」→ Light（ライト）／ Dark（ダーク）")
nav.run()
