"""構成可能な戦略クラス

自動生成された戦略設定(dict)を受け取り、
strategy_base.Strategy として動作するユニバーサル戦略クラス。

対応シグナル: ema_cross, rsi_reversal, rsi_trend, bb_bounce, bb_break,
              donchian_break, atr_break, momentum, wick_reversal,
              consecutive_reversal, hilo_break

対応フィルター: time_filter, session_filter, atr_filter, htf_trend, rsi_range_filter

対応エグジット: 固定/ATR TP/SL, 建値移動, トレーリング, 時間切れ, 逆シグナル,
               分割利確, 連敗停止
"""

import math
import pandas as pd
import numpy as np
from strategy_base import Strategy


# セッション定義 (UTC時間)
SESSIONS = {
    "tokyo":        (0, 9),     # 00:00-09:00 UTC (09:00-18:00 JST)
    "london":       (7, 16),    # 07:00-16:00 UTC
    "newyork":      (13, 22),   # 13:00-22:00 UTC
    "tokyo_london": (0, 16),    # 東京+ロンドン
    "london_ny":    (7, 22),    # ロンドン+NY
}


class ConfigurableStrategy(Strategy):
    """設定dictで動作が決まる汎用戦略クラス"""

    def __init__(self, config: dict, spread: float = 0.2, commission: float = 0.01):
        super().__init__(spread=spread, commission=commission)
        self.config = config
        self.name = config.get("name", "Unnamed")

        self.entry_signal = config.get("entry_signal", {})
        self.entry_filters = config.get("entry_filters", [])
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

    def _add_wick_info(self, df: pd.DataFrame) -> None:
        """ヒゲ情報を計算"""
        body = (df["close"] - df["open"]).abs()
        body = body.replace(0, 1e-10)  # ゼロ除算防止
        df["upper_wick"] = df["high"] - df[["close", "open"]].max(axis=1)
        df["lower_wick"] = df[["close", "open"]].min(axis=1) - df["low"]
        df["wick_ratio_upper"] = df["upper_wick"] / body
        df["wick_ratio_lower"] = df["lower_wick"] / body

    def _add_consecutive(self, df: pd.DataFrame) -> None:
        """連続陽線/陰線カウント"""
        bullish = (df["close"] > df["open"]).astype(int)
        bearish = (df["close"] < df["open"]).astype(int)

        # 連続カウント (NumPyベース)
        bull_count = np.zeros(len(df), dtype=int)
        bear_count = np.zeros(len(df), dtype=int)
        b_vals = bullish.values
        s_vals = bearish.values

        for i in range(1, len(df)):
            if b_vals[i]:
                bull_count[i] = bull_count[i - 1] + 1
            if s_vals[i]:
                bear_count[i] = bear_count[i - 1] + 1

        df["consecutive_bull"] = bull_count
        df["consecutive_bear"] = bear_count

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

        elif sig_type == "wick_reversal":
            wick_ratio = sig.get("wick_ratio", 2.0)
            min_wick_atr = sig.get("min_wick_atr", 0.5)
            wick_atr_period = sig.get("atr_period", 14)
            self._add_atr(df, wick_atr_period)
            self._add_wick_info(df)
            # 下ヒゲが長い → 買いシグナル
            long_lower = (df["wick_ratio_lower"] >= wick_ratio) & (df["lower_wick"] >= df["atr"] * min_wick_atr)
            # 上ヒゲが長い → 売りシグナル
            long_upper = (df["wick_ratio_upper"] >= wick_ratio) & (df["upper_wick"] >= df["atr"] * min_wick_atr)
            df.loc[long_lower, "signal"] = 1
            df.loc[long_upper, "signal"] = -1

        elif sig_type == "consecutive_reversal":
            count = sig.get("consecutive_count", 4)
            self._add_consecutive(df)
            # N本連続陰線後 → 買い
            df.loc[df["consecutive_bear"] >= count, "signal"] = 1
            # N本連続陽線後 → 売り
            df.loc[df["consecutive_bull"] >= count, "signal"] = -1

        elif sig_type == "hilo_break":
            lookback = sig.get("lookback", 20)
            confirm = sig.get("confirm_bars", 1)
            # 直近N本の高値/安値
            rolling_high = df["high"].rolling(window=lookback, min_periods=1).max().shift(1)
            rolling_low = df["low"].rolling(window=lookback, min_periods=1).min().shift(1)
            # ブレイク確認 (confirm_bars本連続でブレイク)
            if confirm <= 1:
                df.loc[df["close"] > rolling_high, "signal"] = 1
                df.loc[df["close"] < rolling_low, "signal"] = -1
            else:
                above = (df["close"] > rolling_high).astype(int)
                below = (df["close"] < rolling_low).astype(int)
                above_sum = above.rolling(window=confirm, min_periods=confirm).sum()
                below_sum = below.rolling(window=confirm, min_periods=confirm).sum()
                df.loc[above_sum >= confirm, "signal"] = 1
                df.loc[below_sum >= confirm, "signal"] = -1

        # フィルター適用
        for filt in self.entry_filters:
            ftype = filt.get("type", "")

            if ftype == "time_filter":
                start_h = filt.get("start_hour", 8)
                end_h = filt.get("end_hour", 20)
                outside = ~((df["hour"] >= start_h) & (df["hour"] < end_h))
                df.loc[outside, "signal"] = 0

            elif ftype == "session_filter":
                session = filt.get("session", "london")
                if session in SESSIONS:
                    s_start, s_end = SESSIONS[session]
                    if s_start < s_end:
                        outside = ~((df["hour"] >= s_start) & (df["hour"] < s_end))
                    else:
                        outside = (df["hour"] >= s_end) & (df["hour"] < s_start)
                    df.loc[outside, "signal"] = 0

            elif ftype == "atr_filter":
                min_atr = filt.get("min_atr", 0.0)
                max_atr = filt.get("max_atr", float("inf"))
                low_vol = df["atr"] < min_atr
                high_vol = df["atr"] > max_atr if max_atr < float("inf") else pd.Series(False, index=df.index)
                df.loc[low_vol | high_vol, "signal"] = 0

            elif ftype == "htf_trend":
                htf_period = filt.get("period", 50)
                htf_mode = filt.get("mode", "trend")  # "trend" or "reversion"
                self._add_higher_tf_trend(df, htf_period)
                if htf_mode == "reversion":
                    # 逆張りモード: H1上昇中はショート禁止、H1下降中はロング禁止
                    # (逆張りシグナル方向がH1トレンドに逆らうのは許容)
                    # ただしH1トレンドに完全に逆行するシグナルのみ除去
                    df.loc[(df["signal"] == -1) & (df["htf_trend"] == 1), "signal"] = 0
                    df.loc[(df["signal"] == 1) & (df["htf_trend"] == -1), "signal"] = 0
                else:
                    # 順張りモード: シグナル方向がHTFトレンドと一致する場合のみ
                    df.loc[(df["signal"] == 1) & (df["htf_trend"] != 1), "signal"] = 0
                    df.loc[(df["signal"] == -1) & (df["htf_trend"] != -1), "signal"] = 0

            elif ftype == "rsi_range_filter":
                rsi_period = filt.get("rsi_period", 14)
                rsi_low = filt.get("rsi_low", 30)
                rsi_high = filt.get("rsi_high", 70)
                col = f"rsi_filt_{rsi_period}"
                if col not in df.columns:
                    self._add_rsi(df, rsi_period, col)
                # RSIが範囲外ならシグナル除去
                df.loc[(df[col] < rsi_low) | (df[col] > rsi_high), "signal"] = 0

            elif ftype == "bb_touch_filter":
                # BB外側タッチフィルタ: ロングはBB下限タッチ時のみ、ショートはBB上限タッチ時のみ
                bb_period = filt.get("period", 20)
                bb_std = filt.get("std_mult", 2.0)
                if "bb_lower" not in df.columns:
                    self._add_bb(df, bb_period, bb_std)
                # ロングシグナルはBB下限以下でないと無効
                df.loc[(df["signal"] == 1) & (df["close"] > df["bb_lower"]), "signal"] = 0
                # ショートシグナルはBB上限以上でないと無効
                df.loc[(df["signal"] == -1) & (df["close"] < df["bb_upper"]), "signal"] = 0

            elif ftype == "atr_low_vola_filter":
                # ATR低ボラフィルタ: ATRが直近N期間の中央値以下のみエントリー
                vola_lookback = filt.get("lookback", 100)
                atr_col = "atr"
                if atr_col not in df.columns:
                    self._add_atr(df, 14)
                atr_median = df[atr_col].rolling(window=vola_lookback, min_periods=20).median()
                df.loc[(df["signal"] != 0) & (df[atr_col] > atr_median), "signal"] = 0

            elif ftype == "wick_direction_filter":
                # ヒゲ反転フィルタ: 下ヒゲ長い=ロング候補のみ、上ヒゲ長い=ショート候補のみ
                wick_ratio_thresh = filt.get("wick_ratio", 1.5)
                if "wick_ratio_lower" not in df.columns:
                    self._add_wick_info(df)
                # ロングは下ヒゲが十分長い場合のみ
                df.loc[(df["signal"] == 1) & (df["wick_ratio_lower"] < wick_ratio_thresh), "signal"] = 0
                # ショートは上ヒゲが十分長い場合のみ
                df.loc[(df["signal"] == -1) & (df["wick_ratio_upper"] < wick_ratio_thresh), "signal"] = 0

        return df

    # ----------------------------------------------------------------
    # エントリー / エグジット (互換用 - 高速バックテストで使わない)
    # ----------------------------------------------------------------
    def entry_logic(self, row: pd.Series, position: dict | None) -> dict | None:
        if position is not None or row["signal"] == 0:
            return None
        return {
            "direction": "long" if row["signal"] == 1 else "short",
            "entry_price": row["close"],
            "entry_time": row["timestamp"],
        }

    def exit_logic(self, row: pd.Series, position: dict) -> bool:
        return row["signal"] != 0 and row["signal"] != (1 if position["direction"] == "long" else -1)

    # ----------------------------------------------------------------
    # 高速バックテスト (NumPy配列ベース)
    # ----------------------------------------------------------------
    def backtest(self, df: pd.DataFrame, initial_balance: float = 100000) -> list["Trade"]:
        from strategy_base import Trade

        df = self.generate_signal(df)
        n = len(df)
        if n == 0:
            return []

        # NumPy配列に変換
        signals = df["signal"].values
        closes = df["close"].values
        highs = df["high"].values
        lows = df["low"].values
        timestamps = df["timestamp"].values
        atrs = df["atr"].values if "atr" in df.columns else np.full(n, 0.1)

        rules = self.exit_rules
        spread_cost = self.spread
        commission_cost = self.commission * 2

        # TP/SL パラメータ
        tp_type = rules.get("tp_type", "fixed")
        sl_type = rules.get("sl_type", "fixed")
        tp_pips = rules.get("tp_pips", 0.3)
        tp_atr_mult = rules.get("tp_atr_mult", 2.0)
        sl_pips = rules.get("sl_pips", 0.2)
        sl_atr_mult = rules.get("sl_atr_mult", 1.5)
        max_bars = int(rules.get("max_bars", 0))
        reverse_exit = bool(rules.get("reverse_signal_exit", False))
        use_trailing = bool(rules.get("trailing", False))
        use_breakeven = bool(rules.get("breakeven", False))

        # トレーリング設定
        trail_type = rules.get("trail_type", "fixed")
        trail_distance_fixed = rules.get("trail_distance", 0.2)
        trail_atr_mult = rules.get("trail_atr_mult", 1.0)
        be_trigger = rules.get("be_trigger_pips", 0.15)

        # 分割利確設定
        use_partial = bool(rules.get("partial_tp", False))
        partial_ratio = rules.get("partial_ratio", 0.5)  # クローズする割合
        partial_tp_ratio = rules.get("partial_tp_ratio", 0.5)  # TP距離の何割で発動

        # 連敗停止
        use_loss_streak_stop = bool(rules.get("loss_streak_stop", False))
        max_consecutive_losses = int(rules.get("max_consecutive_losses", 5))

        trades = []
        consecutive_losses = 0
        i = 0

        while i < n:
            # 連敗停止チェック
            if use_loss_streak_stop and consecutive_losses >= max_consecutive_losses:
                # 次のシグナルが出るまでスキップ (リセット)
                consecutive_losses = 0
                # 一定本数スキップ
                i += max_bars if max_bars > 0 else 60
                continue

            sig = signals[i]
            if sig == 0:
                i += 1
                continue

            # エントリー
            direction = 1 if sig == 1 else -1
            entry_price = closes[i]
            entry_time = timestamps[i]
            atr_entry = atrs[i]

            # TP/SL計算
            if tp_type == "fixed":
                tp_dist = tp_pips
            else:
                tp_dist = atr_entry * tp_atr_mult

            if sl_type == "fixed":
                sl_dist = sl_pips
            else:
                sl_dist = atr_entry * sl_atr_mult

            if direction == 1:
                tp_level = entry_price + tp_dist
                sl_level = entry_price - sl_dist
            else:
                tp_level = entry_price - tp_dist
                sl_level = entry_price + sl_dist

            # 分割利確レベル
            partial_done = False
            if use_partial:
                partial_level = entry_price + (tp_dist * partial_tp_ratio * direction)

            # トレーリング用
            best_price = entry_price
            if use_trailing:
                if trail_type == "atr_mult":
                    t_dist = atr_entry * trail_atr_mult
                else:
                    t_dist = trail_distance_fixed

            # エグジット探索
            bars_held = 0
            j = i + 1
            exited = False
            partial_pnl = 0.0
            remaining_ratio = 1.0

            while j < n:
                bars_held += 1
                h = highs[j]
                l = lows[j]
                c = closes[j]

                # 分割利確判定
                if use_partial and not partial_done:
                    if direction == 1 and h >= partial_level:
                        partial_pnl = (partial_level - entry_price) * partial_ratio
                        remaining_ratio = 1.0 - partial_ratio
                        partial_done = True
                    elif direction == -1 and l <= partial_level:
                        partial_pnl = (entry_price - partial_level) * partial_ratio
                        remaining_ratio = 1.0 - partial_ratio
                        partial_done = True

                # TP判定
                if direction == 1 and h >= tp_level:
                    exited = True
                    break
                if direction == -1 and l <= tp_level:
                    exited = True
                    break

                # SL判定
                if direction == 1 and l <= sl_level:
                    exited = True
                    break
                if direction == -1 and h >= sl_level:
                    exited = True
                    break

                # 建値移動
                if use_breakeven:
                    if direction == 1 and c >= entry_price + be_trigger:
                        sl_level = max(sl_level, entry_price + 0.01)
                    elif direction == -1 and c <= entry_price - be_trigger:
                        sl_level = min(sl_level, entry_price - 0.01)

                # トレーリング
                if use_trailing:
                    if direction == 1:
                        if c > best_price:
                            best_price = c
                            sl_level = max(sl_level, c - t_dist)
                    else:
                        if c < best_price:
                            best_price = c
                            sl_level = min(sl_level, c + t_dist)

                # 時間切れ
                if max_bars > 0 and bars_held >= max_bars:
                    exited = True
                    break

                # 逆シグナル
                if reverse_exit:
                    s = signals[j]
                    if direction == 1 and s == -1:
                        exited = True
                        break
                    if direction == -1 and s == 1:
                        exited = True
                        break

                j += 1

            if exited:
                exit_price = closes[j]
                exit_time = timestamps[j]
                if direction == 1:
                    raw_pnl = (exit_price - entry_price) * remaining_ratio + partial_pnl
                else:
                    raw_pnl = (entry_price - exit_price) * remaining_ratio + partial_pnl
                pnl = raw_pnl - spread_cost - commission_cost

                trades.append(Trade(
                    entry_time=pd.Timestamp(entry_time),
                    exit_time=pd.Timestamp(exit_time),
                    direction="long" if direction == 1 else "short",
                    entry_price=entry_price,
                    exit_price=exit_price,
                    pnl=pnl,
                ))

                # 連敗カウント
                if pnl < 0:
                    consecutive_losses += 1
                else:
                    consecutive_losses = 0

                i = j + 1
            else:
                i = j if j < n else j
                break

        return trades
