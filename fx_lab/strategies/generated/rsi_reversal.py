"""RSI逆張り戦略

RSIが30以下 → 買い（売られすぎからの反転狙い）
RSIが70以上 → 売り（買われすぎからの反転狙い）
RSIが40-60の中間帯に戻ったらエグジット
"""

import pandas as pd
import numpy as np
from strategy_base import Strategy


class RsiReversalStrategy(Strategy):
    name = "RSI_Reversal"

    def __init__(self, period: int = 14, oversold: float = 30, overbought: float = 70,
                 exit_lower: float = 40, exit_upper: float = 60,
                 spread: float = 0.2, commission: float = 0.01):
        super().__init__(spread=spread, commission=commission)
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
        self.exit_lower = exit_lower
        self.exit_upper = exit_upper

    def _calc_rsi(self, series: pd.Series, period: int) -> pd.Series:
        delta = series.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)

        avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(50)

    def generate_signal(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["rsi"] = self._calc_rsi(df["close"], self.period)

        df["signal"] = 0
        df.loc[df["rsi"] <= self.oversold, "signal"] = 1   # 買い
        df.loc[df["rsi"] >= self.overbought, "signal"] = -1  # 売り

        return df

    def entry_logic(self, row: pd.Series, position: dict | None) -> dict | None:
        if position is not None:
            return None
        if row["signal"] == 1:
            return {"direction": "long", "entry_price": row["close"], "entry_time": row["timestamp"]}
        elif row["signal"] == -1:
            return {"direction": "short", "entry_price": row["close"], "entry_time": row["timestamp"]}
        return None

    def exit_logic(self, row: pd.Series, position: dict) -> bool:
        rsi = row.get("rsi", 50)
        if position["direction"] == "long" and rsi >= self.exit_upper:
            return True
        if position["direction"] == "short" and rsi <= self.exit_lower:
            return True
        return False
