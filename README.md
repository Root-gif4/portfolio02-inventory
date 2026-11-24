# 在庫管理システム（Portfolio 02）

小さなお店や社内の備品を想定した、**入庫・出庫を記録すると在庫数が自動で計算される** Web アプリです。
ブラウザで操作しますが、データはこの PC の中（SQLite）だけに保存します。

- 在庫数は保存せず、**取引の履歴から計算**（数字がずれない）
- 在庫が **マイナスになる操作は受け付けない**（過去の日付で入れたときも、その後の在庫まで確かめる）
- 確定した取引は書き換えず、**取消は「逆向きの取引」を足す**（記録が残る）
- 在庫切れ・要発注のお知らせ、月別集計、CSV の取り込み（全部正しいときだけ保存）、整合性チェック、バックアップ

| 項目 | 内容 |
| --- | --- |
| 言語 | Python 3.11 |
| 画面 | Streamlit 1.67（ライト／ダーク切り替え） |
| DB | SQLite ＋ SQLAlchemy 2.1 |
| グラフ | Altair 6 |
| テスト | pytest 9.2（83 件） |

## すぐ試す

```powershell
py -3.11 -m venv .venv
```

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

`start.bat` をダブルクリック → ブラウザが開いたら「見本データを入れる」。詳しくは [使い方.md](使い方.md)。

## コマンド

```powershell
.\.venv\Scripts\python.exe -m inventory seed
```

```powershell
.\.venv\Scripts\python.exe -m inventory check
```

```powershell
.\.venv\Scripts\python.exe -m inventory backup
```

`seed`＝空の DB に見本データ、`check`＝整合性チェック（問題があれば終了コード 1）、`backup`＝`data/backups/` にバックアップ。

## テスト

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## フォルダ構成

```
inventory/        業務の処理（画面とは分けてある）
  models.py       テーブルの定義
  db.py           DB の接続（外部キー ON・書き込みは BEGIN IMMEDIATE）
  service.py      マスタ・入出庫・在庫計算・検索・集計（DB の読み書きはここに集める）
  csvio.py        CSV の取り込み・書き出し
  integrity.py    整合性チェック（8 項目）
  backup.py       バックアップ
  seed.py         見本データ
app/              画面（Streamlit）
  streamlit_app.py  入口・メニュー
  common.py       DB の使い方・エラーの出し方など共通の部品
  views/          各ページ
samples/          取り込みを試す CSV（架空）
tests/            自動テスト
docs/             設計書など
data/             DB・ログ・バックアップ（自動で作られる。Git には入れない）
```

## 資料

- [使い方.md](使い方.md)／[ポートフォリオ.md](ポートフォリオ.md)
- [01 要件定義書](docs/01_要件定義書.md)・[02 基本設計書](docs/02_基本設計書.md)（構成図・画面設計）・[03 DB 設計書](docs/03_DB設計書.md)・[04 詳細設計書](docs/04_詳細設計書.md)・[05 テスト仕様書](docs/05_テスト仕様書.md)・[06 セキュリティチェック](docs/06_セキュリティチェック.md)

見本データ・CSV の会社名・商品はすべて架空です。
