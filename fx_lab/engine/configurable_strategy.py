"""構成可能な戦略クラス

自動生成された戦略設定(dict)を受け取り、
strategy_base.Strategy として動作するユニバーサル戦略クラス。
"""

import math
import pandas as pd
import numpy as np
from strategy_base import Strategy


class ConfigurableStrategy(Strategy):
    """設定dictで動作が決まる汎用戦略クラス"""

    def __init__(self, config: dict, spread: float = 0.2, commission: float = 0.01):
        super().__init__(spread=spread, commission=commission)
        self.config = config
        self.name = config.get("name", "Unnamed")

        # エントリーシグナル設定
        self.entry_signal = config.get("entry_signal", {})
        # エントリーフィルター設定
        self.entry_filters = config.get("entry_filters", [])
        # エグジット設定
        self.exit_rules = config.get("exit_rules", {})

    # ----------------------------------------------------------------
    # インジケーター計算
    # ----------------------------------------------------------------
    def _add_ema(self, df: pd.DataFrame, period: int, col_name: str) -> None:
        df[col_name] = df["close"].ewm(span=period, adjust=False).mean()

    def _add_rsi(self, df: pd.DataFrame, period: int, col_name: str) -> None:
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        df[col_name] = (100 - (100 / (1 + rs))).fillna(50)

    def _add_bb(self, df: pd.DataFrame, period: int, std_mult: float) -> None:
        df["bb_mid"] = df["close"].rolling(window=period, min_periods=1).mean()
        bb_std = df["close"].rolling(window=period, min_periods=1).std().fillna(0)
        df["bb_upper"] = df["bb_mid"] + std_mult * bb_std
        df["bb_lower"] = df["bb_mid"] - std_mult * bb_std

    def _add_atr(self, df: pd.DataFrame, period: int) -> None:
        high = df["high"]
        low = df["low"]
        prev_close = df["close"].shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)
        df["atr"] = tr.rolling(window=period, min_periods=1).mean()

    def _add_momentum(self, df: pd.DataFrame, period: int) -> None:
        df["momentum"] = df["close"] - df["close"].shift(period)

    def _add_donchian(self, df: pd.DataFrame, period: int) -> None:
        df["donchian_high"] = df["high"].rolling(window=period, min_periods=1).max()
        df["donchian_low"] = df["low"].rolling(window=period, min_periods=1).min()

    def _add_hour(self, df: pd.DataFrame) -> None:
        df["hour"] = df["timestamp"].dt.hour

    def _add_higher_tf_trend(self, df: pd.DataFrame, period: int) -> None:
        """上位足トレンド: 長期EMAとの比較"""
        htf_period = period * 5
        df["htf_ema"] = df["close"].ewm(span=htf_period, adjust=False).mean()
        df["htf_trend"] = 0
        df.loc[df["close"] > df["htf_ema"], "htf_trend"] = 1
        df.loc[df["close"] < df["htf_ema"], "htf_trend"] = -1

    # ----------------------------------------------------------------
    # シグナル生成
    # ----------------------------------------------------------------
    def generate_signal(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        sig = self.entry_signal
        sig_type = sig.get("type", "ema_cross")

        # 必要なインジケーターを追加
        atr_period = self.exit_rules.get("atr_period", 14)
        self._add_atr(df, atr_period)
        self._add_hour(df)

        df["signal"] = 0

        if sig_type == "ema_cross":
            short_p = sig.get("short_period", 5)
            long_p = sig.get("long_period", 20)
            self._add_ema(df, short_p, "ema_s")
            self._add_ema(df, long_p, "ema_l")
            cross_up = (df["ema_s"] > df["ema_l"]) & (df["ema_s"].shift(1) <= df["ema_l"].shift(1))
            cross_down = (df["ema_s"] < df["ema_l"]) & (df["ema_s"].shift(1) >= df["ema_l"].shift(1))
            df.loc[cross_up, "signal"] = 1
            df.loc[cross_down, "signal"] = -1

        elif sig_type == "rsi_reversal":
            period = sig.get("period", 14)
            oversold = sig.get("oversold", 30)
            overbought = sig.get("overbought", 70)
            self._add_rsi(df, period, "rsi")
            df.loc[df["rsi"] <= oversold, "signal"] = 1
            df.loc[df["rsi"] >= overbought, "signal"] = -1

        elif sig_type == "rsi_trend":
            period = sig.get("period", 14)
            self._add_rsi(df, period, "rsi")
            # RSI50超えで買い、50割れで売り
            cross_up = (df["rsi"] > 50) & (df["rsi"].shift(1) <= 50)
            cross_down = (df["rsi"] < 50) & (df["rsi"].shift(1) >= 50)
            df.loc[cross_up, "signal"] = 1
            df.loc[cross_down, "signal"] = -1

        elif sig_type == "bb_bounce":
            period = sig.get("period", 20)
            std_mult = sig.get("std_mult", 2.0)
            self._add_bb(df, period, std_mult)
            df.loc[df["close"] <= df["bb_lower"], "signal"] = 1
            df.loc[df["close"] >= df["bb_upper"], "signal"] = -1

        elif sig_type == "bb_break":
            period = sig.get("period", 20)
            std_mult = sig.get("std_mult", 2.0)
            self._add_bb(df, period, std_mult)
            break_up = (df["close"] > df["bb_upper"]) & (df["close"].shift(1) <= df["bb_upper"].shift(1))
            break_down = (df["close"] < df["bb_lower"]) & (df["close"].shift(1) >= df["bb_lower"].shift(1))
            df.loc[break_up, "signal"] = 1
            df.loc[break_down, "signal"] = -1

        elif sig_type == "donchian_break":
            period = sig.get("period", 20)
            self._add_donchian(df, period)
            break_up = (df["close"] > df["donchian_high"].shift(1))
            break_down = (df["close"] < df["donchian_low"].shift(1))
            df.loc[break_up, "signal"] = 1
            df.loc[break_down, "signal"] = -1

        elif sig_type == "atr_break":
            period = sig.get("period", 14)
            multiplier = sig.get("multiplier", 1.5)
            self._add_atr(df, period)
            move = (df["close"] - df["close"].shift(1)).abs()
            df.loc[(df["close"] > df["close"].shift(1)) & (move > df["atr"] * multiplier), "signal"] = 1
            df.loc[(df["close"] < df["close"].shift(1)) & (move > df["atr"] * multiplier), "signal"] = -1

        elif sig_type == "momentum":
            period = sig.get("period", 10)
            self._add_momentum(df, period)
            cross_up = (df["momentum"] > 0) & (df["momentum"].shift(1) <= 0)
            cross_down = (df["momentum"] < 0) & (df["momentum"].shift(1) >= 0)
            df.loc[cross_up, "signal"] = 1
            df.loc[cross_down, "signal"] = -1

        # フィルター適用
        for filt in self.entry_filters:
            ftype = filt.get("type", "")

            if ftype == "time_filter":
                start_h = filt.get("start_hour", 8)
                end_h = filt.get("end_hour", 20)
                outside = ~((df["hour"] >= start_h) & (df["hour"] < end_h))
                df.loc[outside, "signal"] = 0

            elif ftype == "atr_filter":
                min_atr = filt.get("min_atr", 0.0)
                max_atr = filt.get("max_atr", float("inf"))
                low_vol = df["atr"] < min_atr
                high_vol = df["atr"] > max_atr if max_atr < float("inf") else pd.Series(False, index=df.index)
                df.loc[low_vol | high_vol, "signal"] = 0

            elif ftype == "htf_trend":
                htf_period = filt.get("period", 50)
                self._add_higher_tf_trend(df, htf_period)
                # トレンドと一致しないシグナルを除去
                df.loc[(df["signal"] == 1) & (df["htf_trend"] != 1), "signal"] = 0
                df.loc[(df["signal"] == -1) & (df["htf_trend"] != -1), "signal"] = 0

        return df

    # ----------------------------------------------------------------
    # エントリー
    # ----------------------------------------------------------------
    def entry_logic(self, row: pd.Series, position: dict | None) -> dict | None:
        if position is not None:
            return None
        if row["signal"] == 0:
            return None

        direction = "long" if row["signal"] == 1 else "short"
        entry_price = row["close"]
        atr = row.get("atr", 0.1)

        pos = {
            "direction": direction,
            "entry_price": entry_price,
            "entry_time": row["timestamp"],
            "atr_at_entry": atr,
            "bars_held": 0,
            "best_price": entry_price,
        }

        # TP/SL計算
        rules = self.exit_rules
        tp_type = rules.get("tp_type", "fixed")
        sl_type = rules.get("sl_type", "fixed")

        if tp_type == "fixed":
            tp_pips = rules.get("tp_pips", 0.3)
            pos["tp"] = entry_price + tp_pips if direction == "long" else entry_price - tp_pips
        elif tp_type == "atr_mult":
            tp_mult = rules.get("tp_atr_mult", 2.0)
            pos["tp"] = entry_price + atr * tp_mult if direction == "long" else entry_price - atr * tp_mult

        if sl_type == "fixed":
            sl_pips = rules.get("sl_pips", 0.2)
            pos["sl"] = entry_price - sl_pips if direction == "long" else entry_price + sl_pips
        elif sl_type == "atr_mult":
            sl_mult = rules.get("sl_atr_mult", 1.5)
            pos["sl"] = entry_price - atr * sl_mult if direction == "long" else entry_price + atr * sl_mult

        return pos

    # ----------------------------------------------------------------
    # エグジット
    # ----------------------------------------------------------------
    def exit_logic(self, row: pd.Series, position: dict) -> bool:
        rules = self.exit_rules
        direction = position["direction"]
        position["bars_held"] = position.get("bars_held", 0) + 1

        price = row["close"]
        high = row["high"]
        low = row["low"]

        # TP判定
        tp = position.get("tp")
        if tp is not None:
            if direction == "long" and high >= tp:
                return True
            if direction == "short" and low <= tp:
                return True

        # SL判定
        sl = position.get("sl")
        if sl is not None:
            if direction == "long" and low <= sl:
                return True
            if direction == "short" and high >= sl:
                return True

        # 建値移動 (breakeven)
        if rules.get("breakeven", False):
            be_trigger = rules.get("be_trigger_pips", 0.15)
            if direction == "long" and price >= position["entry_price"] + be_trigger:
                position["sl"] = position["entry_price"] + 0.01
            elif direction == "short" and price <= position["entry_price"] - be_trigger:
                position["sl"] = position["entry_price"] - 0.01

        # トレーリングストップ
        if rules.get("trailing", False):
            trail_dist = rules.get("trail_distance", 0.2)
            atr = position.get("atr_at_entry", 0.1)
            trail_type = rules.get("trail_type", "fixed")
            if trail_type == "atr_mult":
                trail_dist = atr * rules.get("trail_atr_mult", 1.0)

            best = position.get("best_price", position["entry_price"])
            if direction == "long":
                if price > best:
                    position["best_price"] = price
                    position["sl"] = max(position.get("sl", 0), price - trail_dist)
            else:
                if price < best:
                    position["best_price"] = price
                    position["sl"] = min(position.get("sl", float("inf")), price + trail_dist)

        # 時間切れ決済
        max_bars = rules.get("max_bars", 0)
        if max_bars > 0 and position["bars_held"] >= max_bars:
            return True

        # 逆シグナル決済
        if rules.get("reverse_signal_exit", False):
            sig = row.get("signal", 0)
            if direction == "long" and sig == -1:
                return True
            if direction == "short" and sig == 1:
                return True

        return False
