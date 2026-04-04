"""Paper取引のCSVエクスポート。"""

import csv
import logging
from pathlib import Path

from .models import PaperTrade

logger = logging.getLogger(__name__)

CSV_HEADER = [
    "trade_id",
    "order_id",
    "signal_time",
    "market_id",
    "market_title",
    "direction",
    "entry_price",
    "entry_amount_usd",
    "exit_price",
    "pnl_usd",
    "holding_minutes",
    "result",
    "model_version",
    "created_at",
]


class CsvWriter:
    """PaperTradeをCSVファイルにリアルタイム追記する。"""

    def __init__(self, csv_path: str = "paper_trades.csv"):
        self._path = Path(csv_path)
        self._ensure_header()

    def _ensure_header(self) -> None:
        """ファイルがなければヘッダー付きで作成する。"""
        if not self._path.exists():
            with open(self._path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(CSV_HEADER)
            logger.info("CSV作成: %s", self._path)

    def append(self, trade: PaperTrade) -> None:
        """1件のPaperTradeをCSVに追記する。"""
        try:
            with open(self._path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    trade.trade_id,
                    trade.order_id,
                    trade.signal_time.isoformat(),
                    trade.market_id,
                    trade.market_title,
                    trade.direction,
                    trade.entry_price,
                    trade.entry_amount_usd,
                    trade.exit_price,
                    trade.pnl_usd,
                    trade.holding_minutes,
                    trade.result,
                    trade.model_version,
                    trade.created_at.isoformat(),
                ])
        except Exception as e:
            logger.error("CSV書き込みエラー: %s", e)

    def append_many(self, trades: list[PaperTrade]) -> None:
        for trade in trades:
            self.append(trade)
