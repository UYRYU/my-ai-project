"""コレクター基底クラスと取引データ型。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Trade:
    tx_hash: str
    wallet_address: str
    market_id: str
    market_title: str
    outcome: str  # "Yes" or "No"
    side: str  # "buy" or "sell"
    amount_usdc: float
    price: float
    timestamp: datetime

    @property
    def direction(self) -> str:
        """Buy-Yes / Buy-No / Sell-Yes / Sell-No を返す。"""
        return f"{self.side.capitalize()}-{self.outcome}"


class BaseCollector(ABC):
    """データ取得の抽象基底クラス。差し替え可能なインターフェース。"""

    @abstractmethod
    async def fetch_recent_trades(self, wallet_address: str) -> list[Trade]:
        """指定ウォレットの最近の取引を取得する。"""
        ...

    async def close(self) -> None:
        """リソースのクリーンアップ。"""
        pass
