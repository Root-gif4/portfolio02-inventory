"""バックアップの作成と一覧。"""

from datetime import datetime

import streamlit as st
from common import home_dir, logger, page_header

from inventory import backup
from inventory.db import DB_FILENAME

page_header("バックアップ", "DB（データの入ったファイル）の写しを作ります。大きな取り込みや月末の前に作っておくと安心です。")

home = home_dir()
backup_dir = home / "backups"

with st.container(border=True):
    st.markdown(f"保存先：`{backup_dir}`（新しいものから {backup.KEEP} 個まで残します）")
    if st.button("今すぐバックアップする", type="primary", icon=":material/backup:"):
        try:
            path = backup.create_backup(home / DB_FILENAME, backup_dir)
            st.success(f"バックアップを作りました：{path.name}", icon=":material/check_circle:")
        except FileNotFoundError as exc:
            st.error(str(exc))
        except Exception:
            logger().exception("バックアップの失敗")
            st.error("バックアップを作れませんでした。保存先の空きや権限を確認してください。", icon=":material/error:")

files = backup.list_backups(backup_dir)
st.subheader("バックアップの一覧")
if not files:
    st.caption("まだありません。")
for p in files[:10]:
    c1, c2, c3 = st.columns([4, 2, 2])
    c1.write(f":material/database: {p.name}")
    c2.write(f"{datetime.fromtimestamp(p.stat().st_mtime):%Y-%m-%d %H:%M}・{p.stat().st_size / 1024:,.0f} KB")
    c3.download_button("ダウンロード", p.read_bytes(), file_name=p.name, mime="application/octet-stream", key=f"dl_{p.name}")

with st.expander("バックアップから戻す方法"):
    st.markdown(f"""
1. この画面を閉じ、`start.bat` の黒い窓も閉じます（アプリを止めます）
2. `{home}` の `inventory.db` を別の名前に変えて残します（例：`inventory_old.db`）。`inventory.db-wal`・`inventory.db-shm` があれば、それも別のフォルダへ移します
3. 戻したいバックアップのファイルを `{home}` に写し、名前を `inventory.db` にします
4. `start.bat` で起動し、「整合性チェック」で問題がないか確かめます
""")
