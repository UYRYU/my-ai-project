"""
Live / Paper Trading Module
============================
Paper trading infrastructure for the BTC Trend Long Bot.

Modules
-------
- state_store: JSON-based state persistence
- risk_manager: Position sizing and risk limits
- position_manager: Virtual position tracking
- signal_engine: Signal generation from OHLCV data
- paper_executor: Main paper trading executor
- bitget_feed: Real-time data feed from Bitget
"""

from btc_trend_bot.live.state_store import StateStore
from btc_trend_bot.live.risk_manager import RiskManager
from btc_trend_bot.live.position_manager import PaperPosition, PositionManager
from btc_trend_bot.live.signal_engine import SignalEngine
from btc_trend_bot.live.paper_executor import PaperExecutor
from btc_trend_bot.live.bitget_feed import BitgetFeed

__all__ = [
    "StateStore",
    "RiskManager",
    "PaperPosition",
    "PositionManager",
    "SignalEngine",
    "PaperExecutor",
    "BitgetFeed",
]
