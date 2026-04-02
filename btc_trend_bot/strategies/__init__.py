"""Trading strategies for the BTC Trend Long Bot."""

from btc_trend_bot.strategies.base_strategy import BaseStrategy, Signal
from btc_trend_bot.strategies.trend_long.pullback_strategy import PullbackStrategy
from btc_trend_bot.strategies.trend_long.breakout_strategy import BreakoutStrategy
from btc_trend_bot.strategies.trend_long.reacceleration_strategy import ReaccelerationStrategy
from btc_trend_bot.strategies.trend_long.multi_tf_strategy import MultiTFStrategy

__all__ = [
    "BaseStrategy",
    "Signal",
    "PullbackStrategy",
    "BreakoutStrategy",
    "ReaccelerationStrategy",
    "MultiTFStrategy",
]
