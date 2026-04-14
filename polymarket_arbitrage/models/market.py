"""Data models for Polymarket entities.

Polymarket hierarchy:
  Event -> Market(s) -> Condition -> Token(s) (YES/NO)

A single Event (e.g. "2024 US Election") can contain multiple Markets
(e.g. "Will Biden win?", "Will Trump win?").

Each Market maps to a Condition on-chain, and each Condition has two tokens:
YES and NO.  NegRisk markets group multiple conditions under one event so that
exactly one resolves YES.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class MarketStatus(str, Enum):
    ACTIVE = "active"
    CLOSED = "closed"
    RESOLVED = "resolved"


class ArbitrageType(str, Enum):
    SINGLE_CONDITION = "single_condition"
    NEGRISK_INTRA = "negrisk_intra"
    COMBINATORIAL = "combinatorial"


class ArbitrageDirection(str, Enum):
    LONG = "long"   # buy all outcomes for < $1
    SHORT = "short"  # sell all outcomes for > $1


@dataclass
class Token:
    """A tradable token representing one side of a condition (YES or NO)."""
    token_id: str
    outcome: str  # "Yes" or "No"
    price: float  # current best price [0, 1]
    winner: Optional[bool] = None  # None if unresolved


@dataclass
class Market:
    """A single binary market (one condition with YES/NO tokens)."""
    id: str
    question: str
    condition_id: str
    slug: str
    tokens: list[Token] = field(default_factory=list)
    status: MarketStatus = MarketStatus.ACTIVE
    volume: float = 0.0
    liquidity: float = 0.0
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    description: str = ""

    @property
    def yes_price(self) -> Optional[float]:
        for t in self.tokens:
            if t.outcome.lower() in ("yes", "up"):
                return t.price
        return None

    @property
    def no_price(self) -> Optional[float]:
        for t in self.tokens:
            if t.outcome.lower() in ("no", "down"):
                return t.price
        return None

    @property
    def price_sum(self) -> Optional[float]:
        y, n = self.yes_price, self.no_price
        if y is not None and n is not None:
            return y + n
        return None


@dataclass
class Event:
    """A top-level event containing one or more markets.

    For NegRisk events the markets are mutually exclusive and exhaustive,
    meaning exactly one market resolves YES.
    """
    id: str
    title: str
    slug: str
    markets: list[Market] = field(default_factory=list)
    neg_risk: bool = False  # True for multi-outcome NegRisk events
    description: str = ""

    @property
    def yes_price_sum(self) -> float:
        """Sum of YES prices across all markets in this event."""
        return sum(m.yes_price for m in self.markets if m.yes_price is not None)

    @property
    def market_count(self) -> int:
        return len(self.markets)


@dataclass
class ArbitrageOpportunity:
    """A detected arbitrage opportunity."""
    arb_type: ArbitrageType
    direction: ArbitrageDirection
    events: list[Event]  # involved events
    markets: list[Market]  # involved markets
    price_sum: float  # sum of outcome prices
    raw_profit_per_dollar: float  # profit before fees per $1 invested
    net_profit_per_dollar: float  # profit after fees per $1 invested
    description: str = ""
    timestamp: Optional[datetime] = None

    @property
    def is_profitable(self) -> bool:
        return self.net_profit_per_dollar > 0


@dataclass
class MarketRelationship:
    """A detected logical dependency between two markets."""
    market_a: Market
    market_b: Market
    relationship_type: str  # e.g. "subset", "complement", "mutually_exclusive"
    confidence: float  # 0-1
    description: str = ""
    resolution_vectors: Optional[list[list[int]]] = None
