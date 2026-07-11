"""戦略の共通インターフェース"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import pandas as pd


@dataclass
class Trade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    direction: str  # "long" or "short"
    entry_price: float
    exit_price: float
    pnl: float = 0.0

    @property
    def holding_seconds(self) -> float:
        return (self.exit_time - self.entry_time).total_seconds()


class Strategy(ABC):
    """全戦略が継承する基底クラス"""

    name: str = "BaseStrategy"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        self.spread = spread
        self.commission = commission

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame) -> pd.DataFrame:
        """OHLCデータにシグナル列を追加して返す。
        signal列: 1=買い, -1=売り, 0=なし
        """
        pass

    @abstractmethod
    def entry_logic(self, row: pd.Series, position: dict | None) -> dict | None:
        """エントリー判定。ポジションがなくシグナルがあればエントリー情報を返す。
        Returns: {"direction": "long"|"short", "entry_price": float, "entry_time": Timestamp} or None
        """
        pass

    @abstractmethod
    def exit_logic(self, row: pd.Series, position: dict) -> bool:
        """エグジット判定。Trueならクローズ。"""
        pass

    def backtest(self, df: pd.DataFrame, initial_balance: float = 100000) -> list[Trade]:
        """バックテスト実行。トレードリストを返す。"""
        df = self.generate_signal(df).copy()
        trades: list[Trade] = []
        position: dict | None = None

        for _, row in df.iterrows():
            if position is None:
                position = self.entry_logic(row, position)
            else:
                if self.exit_logic(row, position):
                    trade = self._close_position(row, position)
                    trades.append(trade)
                    position = None

        return trades

    def _close_position(self, row: pd.Series, position: dict) -> Trade:
        direction = position["direction"]
        entry_price = position["entry_price"]
        exit_price = row["close"]

        spread_cost = self.spread
        commission_cost = self.commission * 2  # 往復

        if direction == "long":
            raw_pnl = exit_price - entry_price
        else:
            raw_pnl = entry_price - exit_price

        pnl = raw_pnl - spread_cost - commission_cost

        return Trade(
            entry_time=position["entry_time"],
            exit_time=row["timestamp"],
            direction=direction,
            entry_price=entry_price,
            exit_price=exit_price,
            pnl=pnl,
        )
