"""利用者に見せてよいエラー（理由をそのまま画面に出す）。"""


class InventoryError(Exception):
    """入力の誤りや、在庫がマイナスになるなど業務ルールに反する操作。"""


class NotFoundError(InventoryError):
    """指定した商品・カテゴリ・取引が見つからない。"""
