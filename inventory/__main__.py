"""コマンド：python -m inventory <seed|check|backup>

- seed   ：空の DB に見本データを入れる
- check  ：データ整合性チェック（問題があれば終了コード 1）
- backup ：DB のバックアップを data/backups に作る
"""

from __future__ import annotations

import argparse
import sys

from . import backup, integrity, seed
from .db import DB_FILENAME, default_home, init_db, make_engine, make_session_factory, session_scope
from .errors import InventoryError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m inventory", description="在庫管理システムのコマンド")
    parser.add_argument("command", choices=["seed", "check", "backup"])
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    home = default_home()
    engine = make_engine(home / DB_FILENAME)
    init_db(engine)
    factory = make_session_factory(engine)
    try:
        if args.command == "seed":
            with session_scope(factory) as s:
                stats = seed.seed(s)
            print("見本データを入れました：" + "・".join(f"{k} {v}" for k, v in stats.items()))
        elif args.command == "check":
            with session_scope(factory) as s:
                results = integrity.run_checks(s)
            for r in results:
                print(f"{'OK      ' if r.ok else '問題あり'} {r.name}")
                for p in r.problems[:20]:
                    print(f"    - {p}")
            return 0 if all(r.ok for r in results) else 1
        elif args.command == "backup":
            engine.dispose()
            path = backup.create_backup(home / DB_FILENAME, home / "backups")
            print(f"バックアップを作りました：{path}")
    except InventoryError as exc:
        print(f"エラー：{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
