"""取引データの正規化処理。"""

from src.collector.base import Trade


def normalize_trades(trades: list[Trade]) -> list[Trade]:
    """取引データを正規化する。重複除去・アドレス正規化など。"""
    seen_hashes: set[str] = set()
    normalized: list[Trade] = []

    for trade in trades:
        if trade.tx_hash in seen_hashes:
            continue
        seen_hashes.add(trade.tx_hash)

        # アドレスを小文字に正規化
        trade.wallet_address = trade.wallet_address.lower()
        trade.side = trade.side.lower()
        trade.outcome = trade.outcome.capitalize()

        normalized.append(trade)

    # タイムスタンプでソート
    normalized.sort(key=lambda t: t.timestamp)
    return normalized
