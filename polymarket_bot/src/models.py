"""Data models for the Polymarket arbitrage bot."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Side(str, Enum):
    YES = "YES"
    NO = "NO"


class TradeAction(str, Enum):
    BUY_YES = "BUY_YES"
    BUY_NO = "BUY_NO"
    SELL_YES = "SELL_YES"
    SELL_NO = "SELL_NO"


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED_TP = "CLOSED_TP"
    CLOSED_SL = "CLOSED_SL"
    CLOSED_TIMEOUT = "CLOSED_TIMEOUT"
    CLOSED_MANUAL = "CLOSED_MANUAL"


@dataclass
class OrderBookLevel:
    price: float
    size: float


@dataclass
class OrderBookSnapshot:
    bids: list[OrderBookLevel] = field(default_factory=list)
    asks: list[OrderBookLevel] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    @property
    def best_bid(self) -> Optional[float]:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        return self.asks[0].price if self.asks else None

    @property
    def best_bid_size(self) -> float:
        return self.bids[0].size if self.bids else 0.0

    @property
    def best_ask_size(self) -> float:
        return self.asks[0].size if self.asks else 0.0

    @property
    def spread(self) -> Optional[float]:
        if self.best_bid is not None and self.best_ask is not None:
            return self.best_ask - self.best_bid
        return None


@dataclass
class MarketToken:
    token_id: str
    outcome: str  # "Yes" or "No"
    price: float = 0.0
    order_book: OrderBookSnapshot = field(default_factory=OrderBookSnapshot)


@dataclass
class Market:
    condition_id: str
    question: str
    slug: str
    tokens: list[MarketToken] = field(default_factory=list)
    active: bool = True
    end_date: Optional[str] = None
    volume: float = 0.0
    last_updated: datetime = field(default_factory=datetime.utcnow)

    @property
    def yes_token(self) -> Optional[MarketToken]:
        for t in self.tokens:
            if t.outcome.upper() == "YES":
                return t
        return None

    @property
    def no_token(self) -> Optional[MarketToken]:
        for t in self.tokens:
            if t.outcome.upper() == "NO":
                return t
        return None


@dataclass
class SignalResult:
    market: Market
    mispricing_score: float = 0.0
    spread_score: float = 0.0
    liquidity_score: float = 0.0
    momentum_score: float = 0.0
    momentum_label: str = "normal"
    confidence_score: float = 0.0
    recommended_action: Optional[TradeAction] = None
    expected_edge: float = 0.0
    reason: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "market_question": self.market.question,
            "condition_id": self.market.condition_id,
            "yes_token_id": self.market.yes_token.token_id if self.market.yes_token else "",
            "no_token_id": self.market.no_token.token_id if self.market.no_token else "",
            "yes_best_bid": self.market.yes_token.order_book.best_bid if self.market.yes_token else None,
            "yes_best_ask": self.market.yes_token.order_book.best_ask if self.market.yes_token else None,
            "no_best_bid": self.market.no_token.order_book.best_bid if self.market.no_token else None,
            "no_best_ask": self.market.no_token.order_book.best_ask if self.market.no_token else None,
            "mispricing_score": round(self.mispricing_score, 4),
            "spread_score": round(self.spread_score, 4),
            "liquidity_score": round(self.liquidity_score, 4),
            "momentum_score": round(self.momentum_score, 4),
            "momentum_label": self.momentum_label,
            "confidence_score": round(self.confidence_score, 2),
            "recommended_action": self.recommended_action.value if self.recommended_action else None,
            "expected_edge": round(self.expected_edge, 4),
            "reason": self.reason,
        }


@dataclass
class PaperPosition:
    position_id: str
    market: Market
    action: TradeAction
    entry_price: float
    size: float
    entry_time: datetime
    status: PositionStatus = PositionStatus.OPEN
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    pnl: float = 0.0
    signal: Optional[SignalResult] = None

    @property
    def hold_time_sec(self) -> float:
        end = self.exit_time or datetime.utcnow()
        return (end - self.entry_time).total_seconds()

    def to_dict(self) -> dict:
        return {
            "position_id": self.position_id,
            "market_question": self.market.question,
            "condition_id": self.market.condition_id,
            "action": self.action.value,
            "entry_price": self.entry_price,
            "size": self.size,
            "entry_time": self.entry_time.isoformat(),
            "status": self.status.value,
            "exit_price": self.exit_price,
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "pnl": round(self.pnl, 4),
            "hold_time_sec": round(self.hold_time_sec, 1),
        }


@dataclass
class DailySummary:
    date: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0
    avg_hold_time_sec: float = 0.0
    win_rate: float = 0.0
    positions: list[dict] = field(default_factory=list)
