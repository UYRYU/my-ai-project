"""ボラティリティブレイクアウト戦略

直近N本のATR（Average True Range）を計算し、
価格がボリンジャーバンド上限を超えたら買い、下限を割ったら売り。
ATRベースのトレーリングストップでエグジット。
"""

import pandas as pd
import numpy as np
from strategy_base import Strategy


class VolatilityBreakoutStrategy(Strategy):
    name = "Volatility_Breakout"

    def __init__(self, bb_period: int = 20, bb_std: float = 2.0,
                 atr_period: int = 14, atr_sl_multiplier: float = 1.5,
                 spread: float = 0.2, commission: float = 0.01):
        super().__init__(spread=spread, commission=commission)
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.atr_period = atr_period
        self.atr_sl_multiplier = atr_sl_multiplier

    def _calc_atr(self, df: pd.DataFrame, period: int) -> pd.Series:
        high = df["high"]
        low = df["low"]
        close = df["close"].shift(1)
        tr = pd.concat([
            high - low,
            (high - close).abs(),
            (low - close).abs(),
        ], axis=1).max(axis=1)
        return tr.rolling(window=period, min_periods=1).mean()

    def generate_signal(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["bb_mid"] = df["close"].rolling(window=self.bb_period, min_periods=1).mean()
        df["bb_std"] = df["close"].rolling(window=self.bb_period, min_periods=1).std().fillna(0)
        df["bb_upper"] = df["bb_mid"] + self.bb_std * df["bb_std"]
        df["bb_lower"] = df["bb_mid"] - self.bb_std * df["bb_std"]
        df["atr"] = self._calc_atr(df, self.atr_period)

        df["signal"] = 0
        # 上限ブレイクアウト → 買い
        breakout_up = (df["close"] > df["bb_upper"]) & (df["close"].shift(1) <= df["bb_upper"].shift(1))
        # 下限ブレイクアウト → 売り
        breakout_down = (df["close"] < df["bb_lower"]) & (df["close"].shift(1) >= df["bb_lower"].shift(1))

        df.loc[breakout_up, "signal"] = 1
        df.loc[breakout_down, "signal"] = -1

        return df

    def entry_logic(self, row: pd.Series, position: dict | None) -> dict | None:
        if position is not None:
            return None
        if row["signal"] == 1:
            return {
                "direction": "long",
                "entry_price": row["close"],
                "entry_time": row["timestamp"],
                "stop_loss": row["close"] - row["atr"] * self.atr_sl_multiplier,
            }
        elif row["signal"] == -1:
            return {
                "direction": "short",
                "entry_price": row["close"],
                "entry_time": row["timestamp"],
                "stop_loss": row["close"] + row["atr"] * self.atr_sl_multiplier,
            }
        return None

    def exit_logic(self, row: pd.Series, position: dict) -> bool:
        # ATRベースのストップロス
        if position["direction"] == "long":
            if row["low"] <= position.get("stop_loss", 0):
                return True
        elif position["direction"] == "short":
            if row["high"] >= position.get("stop_loss", float("inf")):
                return True

        # 逆シグナルでもエグジット
        if position["direction"] == "long" and row["signal"] == -1:
            return True
        if position["direction"] == "short" and row["signal"] == 1:
            return True

        return False
