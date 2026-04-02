"""Abstract base classes for exchange adapters."""

from abc import ABC, abstractmethod
from typing import Optional

import pandas as pd

from btc_trend_bot.exchange.models import (
    ExchangeConfig,
    OrderRequest,
    OrderResult,
    Ticker,
)


class BaseExchange(ABC):
    """Base class for public exchange operations."""

    def __init__(self, config: ExchangeConfig):
        self.config = config

    @abstractmethod
    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: Optional[str] = None,
        limit: int = 1000,
    ) -> pd.DataFrame:
        """Fetch OHLCV candle data.

        Args:
            symbol: Trading pair symbol (e.g. "BTCUSDT").
            timeframe: Candle timeframe (e.g. "1h", "4h", "1d").
            since: ISO-format start datetime string.
            limit: Maximum number of candles to return.

        Returns:
            DataFrame with datetime index and columns: open, high, low, close, volume.
        """
        ...

    @abstractmethod
    def fetch_ticker(self, symbol: str) -> Ticker:
        """Fetch current ticker information for a symbol."""
        ...

    @abstractmethod
    def get_server_time(self) -> pd.Timestamp:
        """Get the exchange server time."""
        ...


class BasePrivateExchange(BaseExchange):
    """Base class for authenticated exchange operations."""

    @abstractmethod
    def place_order(self, order: OrderRequest) -> OrderResult:
        """Place a new order on the exchange."""
        ...

    @abstractmethod
    def cancel_order(self, order_id: str, symbol: str) -> bool:
        """Cancel an existing order. Returns True if successfully cancelled."""
        ...

    @abstractmethod
    def get_balance(self, currency: str = "USDT") -> float:
        """Get available balance for a currency."""
        ...

    @abstractmethod
    def get_open_orders(self, symbol: str) -> list[OrderResult]:
        """Get all open/unfilled orders for a symbol."""
        ...

    @abstractmethod
    def get_position(self, symbol: str) -> Optional[dict]:
        """Get current position for a symbol. Returns None if no position."""
        ...
