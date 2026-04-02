"""Multi-TF Trend Hold Strategy -- multi-timeframe alignment with profit focus.

Single-timeframe strategy that uses multiple EMA alignments as a proxy for
multi-timeframe confirmation.  Designed for selective entries with wider stops
to allow holding through normal retracements for bigger gains.  Includes
anti-FOMO extension check and cooldown between entries.
"""

from __future__ import annotations

import pandas as pd
from loguru import logger

from btc_trend_bot.strategies.base_strategy import BaseStrategy, Signal


class MultiTFTrendHoldStrategy(BaseStrategy):
    """Enter long on full EMA alignment with multi-TF proxy filters."""

    def __init__(self, config: dict | None = None) -> None:
        config = config or {}
        super().__init__(name="multi_tf_trend_hold", config=config)

        self.trend_strength_min: float = config.get("trend_strength_min", 0.5)
        self.rsi_min: float = config.get("rsi_min", 45)
        self.rsi_max: float = config.get("rsi_max", 70)
        self.adx_min: float = config.get("adx_min", 20)
        self.max_extension_pct: float = config.get("max_extension_pct", 12.0)
        self.cooldown_bars: int = config.get("cooldown_bars", 10)
        self.atr_sl_mult: float = config.get("atr_sl_mult", 2.5)

    # ------------------------------------------------------------------
    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        """Scan *df* for high-conviction trend-aligned entries."""

        signals: list[Signal] = []

        if df.empty or len(df) < 2:
            return signals

        close = df["close"]
        rsi = df["rsi"]
        atr = df["atr"]
        adx = df["adx"]
        plus_di = df["plus_di"]
        minus_di = df["minus_di"]
        ema20 = df["ema20"]
        ema50 = df["ema50"]
        ema200 = df["ema200"]
        vwap = df["vwap"]
        volume = df["volume"]
        volume_sma = df["volume_sma"]
        trend_regime = df["trend_regime"]
        trend_strength = df["trend_strength"]
        overextended = df["overextended"]

        last_signal_bar: int = -self.cooldown_bars - 1

        for i in range(1, len(df)):
            # ---- Regime filter ----
            if trend_regime.iloc[i] != "bull":
                continue

            if pd.isna(trend_strength.iloc[i]) or trend_strength.iloc[i] <= self.trend_strength_min:
                continue

            # ---- Not overextended ----
            if overextended.iloc[i]:
                continue

            # ---- Cooldown ----
            if (i - last_signal_bar) < self.cooldown_bars:
                continue

            # ---- Full EMA alignment: EMA20 > EMA50 > EMA200 ----
            if pd.isna(ema20.iloc[i]) or pd.isna(ema50.iloc[i]) or pd.isna(ema200.iloc[i]):
                continue
            if not (ema20.iloc[i] > ema50.iloc[i] > ema200.iloc[i]):
                continue

            # ---- RSI in range and rising ----
            if pd.isna(rsi.iloc[i]) or pd.isna(rsi.iloc[i - 1]):
                continue
            if not (self.rsi_min <= rsi.iloc[i] <= self.rsi_max):
                continue
            if rsi.iloc[i] <= rsi.iloc[i - 1]:
                continue

            # ---- Close above VWAP ----
            if pd.isna(vwap.iloc[i]) or close.iloc[i] <= vwap.iloc[i]:
                continue

            # ---- ADX and directional alignment ----
            if pd.isna(adx.iloc[i]) or adx.iloc[i] <= self.adx_min:
                continue
            if pd.isna(plus_di.iloc[i]) or pd.isna(minus_di.iloc[i]):
                continue
            if plus_di.iloc[i] <= minus_di.iloc[i]:
                continue

            # ---- Volume at least average ----
            if pd.isna(volume_sma.iloc[i]) or volume.iloc[i] <= volume_sma.iloc[i] * 0.9:
                continue

            # ---- Anti-FOMO: price not too far above EMA200 ----
            max_price = ema200.iloc[i] * (1 + self.max_extension_pct / 100)
            if close.iloc[i] > max_price:
                continue

            # ---- Stop loss (wider for holding) ----
            if pd.isna(atr.iloc[i]):
                continue
            stop_loss = close.iloc[i] - self.atr_sl_mult * atr.iloc[i]

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
                        f"Multi-TF trend hold: full EMA alignment "
                        f"(EMA20={ema20.iloc[i]:.2f} > EMA50={ema50.iloc[i]:.2f} > EMA200={ema200.iloc[i]:.2f}), "
                        f"RSI={rsi.iloc[i]:.1f} rising, ADX={adx.iloc[i]:.1f}, "
                        f"above VWAP, trend_strength={trend_strength.iloc[i]:.2f}"
                    ),
                    "rsi": round(float(rsi.iloc[i]), 2),
                    "adx": round(float(adx.iloc[i]), 2),
                    "trend_strength": round(float(trend_strength.iloc[i]), 4),
                    "ema_spread_pct": round(
                        (ema20.iloc[i] / ema200.iloc[i] - 1) * 100, 2
                    ),
                    "atr": round(float(atr.iloc[i]), 2),
                },
            )
            signals.append(signal)
            logger.info(
                "MultiTFTrendHold signal at {}: entry={:.2f}, sl={:.2f}, RSI={:.1f}, ADX={:.1f}",
                ts,
                close.iloc[i],
                stop_loss,
                rsi.iloc[i],
                adx.iloc[i],
            )
            last_signal_bar = i

        return signals

    # ------------------------------------------------------------------
    def get_param_space(self) -> dict:
        """Return optimizable parameter ranges."""
        return {
            "trend_strength_min": (0.3, 0.7),
            "rsi_min": (35, 55),
            "rsi_max": (60, 80),
            "adx_min": (15, 30),
            "max_extension_pct": (8.0, 20.0),
            "atr_sl_mult": (2.0, 4.0),
        }
