"""Real-time data feed from Bitget for paper trading.

Wraps ``BitgetPublicClient`` to provide a simple interface for fetching
the latest OHLCV bars and current price, with transparent caching so
that a transient API failure does not crash the paper-trading loop.
"""

from __future__ import annotations

import os

import pandas as pd
from loguru import logger

from btc_trend_bot.exchange.bitget_public import BitgetPublicClient
from btc_trend_bot.exchange.models import ExchangeConfig


class BitgetFeed:
    """Fetches latest OHLCV data from Bitget for paper trading use."""

    def __init__(self, config: dict | None = None) -> None:
        cfg = config or {}
        init_kwargs = {
            k: v for k, v in cfg.items()
            if k in ExchangeConfig.__dataclass_fields__
        }
        # Override with env vars if available
        if os.environ.get("BITGET_API_KEY"):
            init_kwargs.setdefault("api_key", os.environ["BITGET_API_KEY"])
        if os.environ.get("BITGET_API_SECRET"):
            init_kwargs.setdefault("api_secret", os.environ["BITGET_API_SECRET"])
        if os.environ.get("BITGET_PASSPHRASE"):
            init_kwargs.setdefault("passphrase", os.environ["BITGET_PASSPHRASE"])
        exchange_config = ExchangeConfig(**init_kwargs)
        self.client = BitgetPublicClient(exchange_config)
        self.symbol: str = cfg.get("symbol", "BTCUSDT")
        self.cache: dict[str, pd.DataFrame] = {}  # timeframe -> last fetched df
        logger.info("BitgetFeed initialised for {}", self.symbol)

    def get_latest_bars(
        self, timeframe: str = "1h", count: int = 500
    ) -> pd.DataFrame:
        """Fetch the latest *count* bars from Bitget.

        On success the result is cached so that a subsequent failure can
        fall back to slightly stale data rather than returning nothing.

        Parameters
        ----------
        timeframe : str
            Candle timeframe (e.g. ``"1h"``, ``"4h"``).
        count : int
            Number of bars to request (capped at 1000 by the exchange).

        Returns
        -------
        pd.DataFrame
            OHLCV DataFrame with a DatetimeIndex, or an empty DataFrame
            if both the live request and the cache miss.
        """
        try:
            df = self.client.fetch_ohlcv(
                self.symbol, timeframe, limit=min(count, 1000)
            )
            if not df.empty:
                self.cache[timeframe] = df
            return df
        except Exception as exc:
            logger.error("Failed to fetch OHLCV data: {}", exc)
            if timeframe in self.cache:
                logger.warning(
                    "Returning cached data ({} bars) for {} {}",
                    len(self.cache[timeframe]),
                    self.symbol,
                    timeframe,
                )
                return self.cache[timeframe]
            return pd.DataFrame()

    def get_current_price(self) -> float:
        """Get the current BTC price from the exchange ticker.

        Returns
        -------
        float
            The last traded price, or ``0.0`` if the request fails.
        """
        try:
            ticker = self.client.fetch_ticker(self.symbol)
            return ticker.last_price
        except Exception as exc:
            logger.error("Failed to fetch ticker price: {}", exc)
            return 0.0
