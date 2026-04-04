"""Generate trading signals from live/streaming OHLCV data.

Uses the existing strategy classes (pullback, breakout, reacceleration,
multi_tf, and strict variants) and the shared FeatureEngineer to produce
``Signal`` objects that the paper executor can act on.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
from loguru import logger

from btc_trend_bot.feature_engineering import FeatureEngineer
from btc_trend_bot.strategies.base_strategy import BaseStrategy, Signal


class SignalEngine:
    """Generate signals from incoming OHLCV data using configured strategies."""

    def __init__(self, config: dict) -> None:
        self.strategies: list[BaseStrategy] = []
        self.fe = FeatureEngineer(config.get("trend_detection", {}))
        self.min_bars: int = config.get("min_bars_required", 250)
        self._multi_tf_strategies: list[BaseStrategy] = []  # strategies needing higher_tf
        self._setup_strategies(config)

    # ------------------------------------------------------------------
    # Strategy initialisation
    # ------------------------------------------------------------------

    def _setup_strategies(self, config: dict) -> None:
        """Instantiate strategy objects from configuration."""
        from btc_trend_bot.strategies.trend_long.pullback_strategy import PullbackStrategy
        from btc_trend_bot.strategies.trend_long.breakout_strategy import BreakoutStrategy
        from btc_trend_bot.strategies.trend_long.reacceleration_strategy import ReaccelerationStrategy
        from btc_trend_bot.strategies.trend_long.multi_tf_strategy import MultiTFStrategy

        strategy_configs: dict = config.get("strategies", {})
        enabled: list[str] = config.get(
            "enabled_strategies", ["pullback", "breakout", "reacceleration"]
        )

        strategy_map: dict[str, type[BaseStrategy]] = {
            "pullback": PullbackStrategy,
            "breakout": BreakoutStrategy,
            "reacceleration": ReaccelerationStrategy,
            "multi_tf": MultiTFStrategy,
        }

        # Add strict variants if available
        try:
            from btc_trend_bot.strategies.trend_long.pullback_strict import PullbackStrictStrategy
            strategy_map["pullback_strict"] = PullbackStrictStrategy
        except ImportError:
            pass
        try:
            from btc_trend_bot.strategies.trend_long.breakout_confirmed import BreakoutConfirmedStrategy
            strategy_map["breakout_confirmed"] = BreakoutConfirmedStrategy
        except ImportError:
            pass
        try:
            from btc_trend_bot.strategies.trend_long.reacceleration_quality import ReaccelerationQualityStrategy
            strategy_map["reacceleration_quality"] = ReaccelerationQualityStrategy
        except ImportError:
            pass
        try:
            from btc_trend_bot.strategies.trend_long.multi_tf_trend_hold import MultiTFTrendHoldStrategy
            strategy_map["multi_tf_trend_hold"] = MultiTFTrendHoldStrategy
        except ImportError:
            pass

        for name in enabled:
            cls = strategy_map.get(name)
            if cls is None:
                logger.warning("Unknown strategy name '{}', skipping", name)
                continue
            strat = cls(strategy_configs.get(name, {}))
            self.strategies.append(strat)
            # Track strategies that need higher TF data
            if hasattr(strat, "set_higher_tf_data"):
                self._multi_tf_strategies.append(strat)
            logger.info("Enabled strategy: {}", name)

        if not self.strategies:
            logger.warning("No strategies enabled -- SignalEngine will produce no signals")

    # ------------------------------------------------------------------
    # Higher timeframe data
    # ------------------------------------------------------------------

    @property
    def needs_higher_tf(self) -> bool:
        """Return True if any enabled strategy requires higher timeframe data."""
        return len(self._multi_tf_strategies) > 0

    def update_higher_tf(self, higher_tf_df: pd.DataFrame) -> None:
        """Pass higher timeframe data to all strategies that need it.

        Also adds features (EMA, trend_regime, etc.) to the higher-TF
        DataFrame before handing it to the strategies.
        """
        if higher_tf_df.empty:
            logger.warning("Empty higher_tf DataFrame, skipping update")
            return

        # Add features to higher TF data
        htf_featured = self.fe.add_all_features(higher_tf_df)

        for strat in self._multi_tf_strategies:
            strat.set_higher_tf_data(htf_featured)

        logger.debug(
            "Updated higher TF data for {} strategy(ies): {} bars",
            len(self._multi_tf_strategies),
            len(htf_featured),
        )

    # ------------------------------------------------------------------
    # Signal generation
    # ------------------------------------------------------------------

    def process_bar(self, df: pd.DataFrame, precomputed: bool = False) -> list[Signal]:
        """Process a DataFrame of OHLCV bars and return signals for the latest bar.

        Parameters
        ----------
        df : pd.DataFrame
            Must contain at least ``min_bars`` rows of OHLCV data with a
            DatetimeIndex.  The engine adds all technical features, then
            asks each strategy for signals.  Only signals whose timestamp
            matches the **last** bar are returned.
        precomputed : bool
            If True, skip feature engineering (df already has indicators).

        Returns
        -------
        list[Signal]
            Typically 0 or 1 signals; could be more if multiple strategies
            fire on the same bar.
        """
        if len(df) < self.min_bars:
            logger.debug(
                "Insufficient bars ({} < {}), skipping signal generation",
                len(df),
                self.min_bars,
            )
            return []

        df_featured = df if precomputed else self.fe.add_all_features(df)
        latest_time = df_featured.index[-1]

        all_signals: list[Signal] = []
        for strategy in self.strategies:
            try:
                signals = strategy.generate_signals(df_featured)
                if signals:
                    latest_signals = [s for s in signals if s.timestamp == latest_time]
                    all_signals.extend(latest_signals)
            except Exception as exc:
                logger.error(
                    "Strategy '{}' raised an error: {}",
                    strategy.name,
                    exc,
                )

        if all_signals:
            logger.info(
                "Generated {} signal(s) at {}: {}",
                len(all_signals),
                latest_time,
                [s.strategy_name for s in all_signals],
            )

        return all_signals

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_active_strategy_names(self) -> list[str]:
        """Return the names of all loaded strategies."""
        return [s.name for s in self.strategies]
