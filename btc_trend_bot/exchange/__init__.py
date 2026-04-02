"""Exchange abstraction layer for BTC Trend Long Bot."""

from btc_trend_bot.exchange.base import BaseExchange, BasePrivateExchange
from btc_trend_bot.exchange.bitget_private import BitgetPrivateClient
from btc_trend_bot.exchange.bitget_public import BitgetPublicClient
from btc_trend_bot.exchange.models import (
    ExchangeConfig,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderType,
    PositionSide,
    Ticker,
)

__all__ = [
    "BaseExchange",
    "BasePrivateExchange",
    "BitgetPrivateClient",
    "BitgetPublicClient",
    "ExchangeConfig",
    "OrderRequest",
    "OrderResult",
    "OrderSide",
    "OrderType",
    "PositionSide",
    "Ticker",
]
