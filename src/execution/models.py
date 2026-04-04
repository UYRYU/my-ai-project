"""Execution層のデータモデル。"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4


class TradingMode(Enum):
    PAPER = "paper"
    LIVE = "live"
    DRY_RUN = "dry-run"


class OrderStatus(Enum):
    PENDING = "pending"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass
class Order:
    order_id: str = field(default_factory=lambda: uuid4().hex[:12])
    signal_market_id: str = ""
    signal_direction: str = ""
    market_id: str = ""
    market_title: str = ""
    side: str = ""  # "buy" or "sell"
    outcome: str = ""  # "Yes" or "No"
    amount_usdc: float = 0.0
    limit_price: float = 0.0
    status: OrderStatus = OrderStatus.PENDING
    mode: TradingMode = TradingMode.PAPER
    reject_reason: str = ""
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def direction(self) -> str:
        return f"{self.side.capitalize()}-{self.outcome}"


@dataclass
class Fill:
    fill_id: str = field(default_factory=lambda: uuid4().hex[:12])
    order_id: str = ""
    market_id: str = ""
    side: str = ""
    outcome: str = ""
    amount_usdc: float = 0.0
    fill_price: float = 0.0
    mode: TradingMode = TradingMode.PAPER
    filled_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def pnl_at_price(self) -> float:
        """現在価格 = fill_price として暫定PnLを0とする。実決済時に計算。"""
        return 0.0


@dataclass
class PnLRecord:
    record_id: str = field(default_factory=lambda: uuid4().hex[:12])
    market_id: str = ""
    side: str = ""
    outcome: str = ""
    entry_price: float = 0.0
    amount_usdc: float = 0.0
    realized_pnl: float = 0.0
    mode: TradingMode = TradingMode.PAPER
    recorded_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass
class PaperTrade:
    """Paper取引の完全記録。エントリーから仮想決済まで。"""
    trade_id: str = field(default_factory=lambda: uuid4().hex[:12])
    order_id: str = ""
    signal_time: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    market_id: str = ""
    market_title: str = ""
    direction: str = ""  # "Buy-Yes" etc
    entry_price: float = 0.0
    entry_amount_usd: float = 0.0
    exit_price: float = 0.0
    pnl_usd: float = 0.0
    holding_minutes: float = 0.0
    result: str = ""  # "win" or "loss"
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
