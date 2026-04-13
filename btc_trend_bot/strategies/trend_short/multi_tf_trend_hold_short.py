"""Multi-TF Trend Hold SHORT Strategy -- mirror of multi_tf_trend_hold.

Single-timeframe strategy that uses inverted EMA alignments (EMA20 < EMA50
< EMA200) for downtrend confirmation. Requires RSI in the 30-55 range and
falling, price below VWAP, -DI > +DI. Anti-panic check: price not too far
below EMA200. Wider stops to hold through normal retracements for bigger
short gains.
"""

from __future__ import annotations

import pandas as pd
from loguru import logger

from btc_trend_bot.strategies.base_strategy import BaseStrategy, Signal


class MultiTFTrendHoldShortStrategy(BaseStrategy):
    """Enter short on full bearish EMA alignment with multi-TF proxy filters."""

    def __init__(self, config: dict | None = None) -> None:
        config = config or {}
        super().__init__(name="multi_tf_trend_hold_short", config=config)

        self.trend_strength_min: float = config.get("trend_strength_min", 0.5)
        self.rsi_min: float = config.get("rsi_min", 30)
        self.rsi_max: float = config.get("rsi_max", 55)
        self.adx_min: float = config.get("adx_min", 20)
        self.max_extension_pct: float = config.get("max_extension_pct", 12.0)
        self.cooldown_bars: int = config.get("cooldown_bars", 10)
        self.atr_sl_mult: float = config.get("atr_sl_mult", 2.5)

    # ------------------------------------------------------------------
    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        """Scan *df* for high-conviction bearish trend-aligned entries."""

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

        last_signal_bar: int = -self.cooldown_bars - 1

        for i in range(1, len(df)):
            # ---- Regime filter: must be BEAR ----
            if trend_regime.iloc[i] != "bear":
                continue

            # ---- Trend strength (bear strength) ----
            # trend_strength is bullish-biased; for shorts, use ADX + -DI directly
            if pd.isna(adx.iloc[i]) or pd.isna(minus_di.iloc[i]) or pd.isna(plus_di.iloc[i]):
                continue
            bear_strength = (adx.iloc[i] / 100.0) * (1.0 if minus_di.iloc[i] > plus_di.iloc[i] else 0.0)
            if bear_strength < self.trend_strength_min * 0.5:  # scaled for ADX range
                continue

            # ---- Cooldown ----
            if (i - last_signal_bar) < self.cooldown_bars:
                continue

            # ---- Full bearish EMA alignment: EMA20 < EMA50 < EMA200 ----
            if pd.isna(ema20.iloc[i]) or pd.isna(ema50.iloc[i]) or pd.isna(ema200.iloc[i]):
                continue
            if not (ema20.iloc[i] < ema50.iloc[i] < ema200.iloc[i]):
                continue

            # ---- RSI in bearish range and FALLING ----
            if pd.isna(rsi.iloc[i]) or pd.isna(rsi.iloc[i - 1]):
                continue
            if not (self.rsi_min <= rsi.iloc[i] <= self.rsi_max):
                continue
            if rsi.iloc[i] >= rsi.iloc[i - 1]:  # must be falling
                continue

            # ---- Close BELOW VWAP ----
            if pd.isna(vwap.iloc[i]) or close.iloc[i] >= vwap.iloc[i]:
                continue

            # ---- ADX and bearish directional alignment ----
            if adx.iloc[i] <= self.adx_min:
                continue
            if minus_di.iloc[i] <= plus_di.iloc[i]:  # -DI must dominate
                continue

            # ---- Volume at least average ----
            if pd.isna(volume_sma.iloc[i]) or volume.iloc[i] <= volume_sma.iloc[i] * 0.9:
                continue

            # ---- Anti-panic: price not too far BELOW EMA200 ----
            min_price = ema200.iloc[i] * (1 - self.max_extension_pct / 100)
            if close.iloc[i] < min_price:
                continue

            # ---- Stop loss (ABOVE entry for shorts) ----
            if pd.isna(atr.iloc[i]):
                continue
            stop_loss = close.iloc[i] + self.atr_sl_mult * atr.iloc[i]

            if stop_loss <= close.iloc[i]:
                stop_loss = close.iloc[i] + atr.iloc[i]

            ts = df.index[i] if isinstance(df.index, pd.DatetimeIndex) else pd.Timestamp.now()

            signal = Signal(
                timestamp=ts,
                direction="short",
                entry_price=close.iloc[i],
                stop_loss=stop_loss,
                take_profit=None,
                size_pct=100.0,
                strategy_name=self.name,
                metadata={
                    "reason": (
                        f"Multi-TF short hold: full bearish EMA alignment "
                        f"(EMA20={ema20.iloc[i]:.2f} < EMA50={ema50.iloc[i]:.2f} < EMA200={ema200.iloc[i]:.2f}), "
                        f"RSI={rsi.iloc[i]:.1f} falling, ADX={adx.iloc[i]:.1f}, "
                        f"below VWAP, bear_strength={bear_strength:.2f}"
                    ),
                    "rsi": round(float(rsi.iloc[i]), 2),
                    "adx": round(float(adx.iloc[i]), 2),
                    "bear_strength": round(bear_strength, 4),
                    "ema_spread_pct": round(
                        (1 - ema20.iloc[i] / ema200.iloc[i]) * 100, 2
                    ),
                    "atr": round(float(atr.iloc[i]), 2),
                },
            )
            signals.append(signal)
            logger.info(
                "MultiTFTrendHoldShort signal at {}: entry={:.2f}, sl={:.2f}, RSI={:.1f}, ADX={:.1f}",
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
        return {
            "trend_strength_min": (0.3, 0.7),
            "rsi_min": (20, 45),
            "rsi_max": (45, 65),
            "adx_min": (15, 30),
            "max_extension_pct": (8.0, 20.0),
            "atr_sl_mult": (2.0, 4.0),
        }
