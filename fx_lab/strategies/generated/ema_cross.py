"""EMAクロス戦略

短期EMAが長期EMAを上抜け → 買い
短期EMAが長期EMAを下抜け → 売り
逆シグナルでエグジット
"""

import pandas as pd
from strategy_base import Strategy


class EmaCrossStrategy(Strategy):
    name = "EMA_Cross"

    def __init__(self, short_period: int = 5, long_period: int = 20,
                 spread: float = 0.2, commission: float = 0.01):
        super().__init__(spread=spread, commission=commission)
        self.short_period = short_period
        self.long_period = long_period

    def generate_signal(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["ema_short"] = df["close"].ewm(span=self.short_period, adjust=False).mean()
        df["ema_long"] = df["close"].ewm(span=self.long_period, adjust=False).mean()

        df["signal"] = 0
        # 短期EMAが長期EMAを上抜け
        cross_up = (df["ema_short"] > df["ema_long"]) & (df["ema_short"].shift(1) <= df["ema_long"].shift(1))
        # 短期EMAが長期EMAを下抜け
        cross_down = (df["ema_short"] < df["ema_long"]) & (df["ema_short"].shift(1) >= df["ema_long"].shift(1))

        df.loc[cross_up, "signal"] = 1
        df.loc[cross_down, "signal"] = -1

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
        if position["direction"] == "long" and row["signal"] == -1:
            return True
        if position["direction"] == "short" and row["signal"] == 1:
            return True
        return False
