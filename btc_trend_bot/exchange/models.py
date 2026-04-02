"""Data models for exchange interactions."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import pandas as pd


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"


class PositionSide(Enum):
    LONG = "long"
    SHORT = "short"


@dataclass
class Ticker:
    symbol: str
    last_price: float
    bid: float
    ask: float
    volume_24h: float
    timestamp: pd.Timestamp


@dataclass
class OrderRequest:
    symbol: str
    side: OrderSide
    order_type: OrderType
    size: float
    price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    client_order_id: Optional[str] = None
    leverage: int = 1
    reduce_only: bool = False


@dataclass
class OrderResult:
    order_id: str
    client_order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    size: float
    price: float
    filled_size: float
    status: str  # "filled", "partial", "rejected", "cancelled"
    fee: float
    timestamp: pd.Timestamp
    metadata: dict = field(default_factory=dict)


@dataclass
class ExchangeConfig:
    exchange_name: str = "bitget"
    api_key: str = ""
    api_secret: str = ""
    passphrase: str = ""
    testnet: bool = True
    maker_fee_pct: float = 0.02  # Bitget spot maker
    taker_fee_pct: float = 0.06  # Bitget spot taker
    slippage_bps: float = 5.0  # 5 basis points
    min_order_size_btc: float = 0.0001
    max_leverage: int = 20
    risk_per_trade_pct: float = 2.0
    base_url: str = "https://api.bitget.com"
