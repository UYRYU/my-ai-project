"""Pullback Buy Strategy -- enters long on RSI dips during confirmed bull trends.

Waits for RSI to dip below an oversold threshold then recover, while price
remains above EMA50 and volume confirms. Stop-loss is set at the tighter of
recent swing low or ATR-based distance.
"""

from __future__ import annotations

import pandas as pd
from loguru import logger

from btc_trend_bot.strategies.base_strategy import BaseStrategy, Signal
from btc_trend_bot.indicators.trend import (
    calc_atr,
    calc_ema,
    calc_rsi,
    calc_volume_sma,
)


class PullbackStrategy(BaseStrategy):
    """Buy pullbacks in a confirmed bull trend."""

    def __init__(self, config: dict | None = None) -> None:
        config = config or {}
        super().__init__(name="pullback", config=config)

        # Tuneable parameters with defaults
        self.rsi_oversold: int = config.get("rsi_oversold", 45)
        self.rsi_recovery: int = config.get("rsi_recovery", 55)
        self.ema_period: int = config.get("ema_period", 50)
        self.ema_fast: int = config.get("ema_fast", 20)
        self.atr_period: int = config.get("atr_period", 14)
        self.atr_sl_mult: float = config.get("atr_sl_mult", 2.0)
        self.swing_low_lookback: int = config.get("swing_low_lookback", 10)
        self.volume_sma_period: int = config.get("volume_sma_period", 20)
        self.min_sl_atr_mult: float = config.get("min_sl_atr_mult", 0.75)

    # ------------------------------------------------------------------
    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        """Scan *df* for pullback buy setups in bull regime bars."""

        signals: list[Signal] = []

        if df.empty:
            return signals

        # Pre-compute indicators if not already present
        if "rsi" not in df.columns:
            df = df.copy()
            df["rsi"] = calc_rsi(df, period=14)
        if "ema50" not in df.columns:
            df = df.copy()
            df["ema50"] = calc_ema(df, column="close", period=self.ema_period)
        if "atr" not in df.columns:
            df = df.copy()
            df["atr"] = calc_atr(df, period=self.atr_period)
        if "volume_sma" not in df.columns:
            df = df.copy()
            df["volume_sma"] = calc_volume_sma(df, period=self.volume_sma_period)

        rsi = df["rsi"]
        close = df["close"]
        low = df["low"]
        volume = df["volume"]
        atr = df["atr"]
        ema50 = df["ema50"]
        volume_sma = df["volume_sma"]
        trend_regime = df.get("trend_regime")

        # Track whether RSI has dipped below oversold threshold
        dipped = False

        for i in range(1, len(df)):
            # Only trade in bull regime
            if trend_regime is not None and trend_regime.iloc[i] != "bull":
                dipped = False
                continue

            current_rsi = rsi.iloc[i]
            prev_rsi = rsi.iloc[i - 1]

            # Detect the dip
            if current_rsi < self.rsi_oversold:
                dipped = True
                continue

            # Detect recovery after a dip
            if not dipped:
                continue

            if prev_rsi < self.rsi_recovery and current_rsi >= self.rsi_recovery:
                # Price must be above EMA50
                if close.iloc[i] <= ema50.iloc[i]:
                    continue

                # Volume confirmation
                if pd.isna(volume_sma.iloc[i]) or volume.iloc[i] <= volume_sma.iloc[i]:
                    continue

                # Calculate stop loss
                swing_start = max(0, i - self.swing_low_lookback)
                swing_low = low.iloc[swing_start : i + 1].min()
                atr_sl = close.iloc[i] - self.atr_sl_mult * atr.iloc[i]

                # Use the tighter SL, but enforce a minimum distance
                min_sl = close.iloc[i] - self.min_sl_atr_mult * atr.iloc[i]
                stop_loss = max(swing_low, atr_sl)
                # Ensure SL is not unreasonably tight
                stop_loss = min(stop_loss, min_sl)

                # Ensure SL is below entry
                if stop_loss >= close.iloc[i]:
                    stop_loss = close.iloc[i] - atr.iloc[i]

                ts = df.index[i] if isinstance(df.index, pd.DatetimeIndex) else pd.Timestamp.now()

                signal = Signal(
                    timestamp=ts,
                    direction="long",
                    entry_price=close.iloc[i],
                    stop_loss=stop_loss,
                    take_profit=None,
                    size_pct=100.0,
                    strategy_name=self.name,
                    metadata={
                        "reason": (
                            f"RSI pullback recovery: RSI dipped below {self.rsi_oversold} "
                            f"then recovered above {self.rsi_recovery} "
                            f"(RSI={current_rsi:.1f}), price above EMA{self.ema_period}, "
                            f"volume confirmed"
                        ),
                        "rsi": round(current_rsi, 2),
                        "ema50": round(ema50.iloc[i], 2),
                        "atr": round(atr.iloc[i], 2),
                    },
                )
                signals.append(signal)
                logger.info(
                    "Pullback signal at {}: entry={:.2f}, sl={:.2f}",
                    ts,
                    close.iloc[i],
                    stop_loss,
                )
                dipped = False

        return signals

    # ------------------------------------------------------------------
    def get_param_space(self) -> dict:
        """Return optimizable parameter ranges."""
        return {
            "rsi_oversold": (35, 50),
            "rsi_recovery": (50, 65),
            "ema_fast": (15, 30),
            "atr_sl_mult": (1.0, 3.0),
        }
