"""DB のバックアップ（SQLite の backup 機能で、使用中でも壊れないように写す）。"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

KEEP = 30  # 残すバックアップの数（古いものから消す）


def create_backup(db_path: Path, backup_dir: Path, keep: int = KEEP) -> Path:
    db_path, backup_dir = Path(db_path), Path(backup_dir)
    if not db_path.is_file():
        raise FileNotFoundError("DB ファイルがまだありません。")
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / f"inventory_{datetime.now():%Y%m%d-%H%M%S-%f}.db"
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    for old in list_backups(backup_dir)[keep:]:
        old.unlink(missing_ok=True)
    return dest


def list_backups(backup_dir: Path) -> list[Path]:
    """新しい順。"""
    backup_dir = Path(backup_dir)
    if not backup_dir.is_dir():
        return []
    return sorted(backup_dir.glob("inventory_*.db"), key=lambda p: p.name, reverse=True)
