"""Domain-agnostic primitives for arbitrage detection.

These data classes model the universal structure shared across
prediction markets, sports betting, DeFi, options, and any
domain where mispricing can be detected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


# ── Enums ────────────────────────────────────────────────────────────

class Direction(str, Enum):
    LONG = "long"    # buy the underpriced basket
    SHORT = "short"  # sell the overpriced basket


class ConstraintKind(str, Enum):
    """What mathematical relationship the outcome prices must satisfy."""
    SUM_EQUALS_ONE = "sum_eq_1"          # mutually exclusive & exhaustive
    SUM_LESS_EQUAL_ONE = "sum_le_1"      # mutually exclusive (not exhaustive)
    PAIR_EQUALS_ONE = "pair_eq_1"        # binary YES/NO
    PARITY = "parity"                    # e.g. put-call parity
    TRIANGLE = "triangle"               # triangular inequality (FX / DEX)
    CUSTOM = "custom"


class RelationshipKind(str, Enum):
    SUBSET = "subset"
    SUPERSET = "superset"
    COMPLEMENT = "complement"
    MUTUALLY_EXCLUSIVE = "mutually_exclusive"
    OVERLAPPING = "overlapping"
    EQUIVALENT = "equivalent"            # same thing on different venues
    INDEPENDENT = "independent"


# ── Core data classes ────────────────────────────────────────────────

@dataclass
class Outcome:
    """A single priced outcome / leg / instrument."""
    id: str
    label: str
    price: float          # observed price (0–1 for probabilities, or any float)
    venue: str = ""       # exchange / bookmaker / DEX name
    metadata: dict = field(default_factory=dict)


@dataclass
class Instrument:
    """A group of outcomes that should jointly satisfy a constraint.

    Generalises: Polymarket market, sports bet on one event,
    token pair on a DEX, option chain for one strike.
    """
    id: str
    name: str
    outcomes: list[Outcome] = field(default_factory=list)
    constraint: ConstraintKind = ConstraintKind.SUM_EQUALS_ONE
    venue: str = ""
    category: str = ""        # topic / sport / asset class
    end_date: Optional[datetime] = None
    description: str = ""
    metadata: dict = field(default_factory=dict)

    @property
    def price_sum(self) -> float:
        return sum(o.price for o in self.outcomes)


@dataclass
class Relationship:
    """A detected logical / economic relationship between two instruments."""
    instrument_a: Instrument
    instrument_b: Instrument
    kind: RelationshipKind
    confidence: float = 1.0
    description: str = ""
    resolution_vectors: Optional[list[list[int]]] = None


@dataclass
class Opportunity:
    """A detected arbitrage / mispricing opportunity."""
    domain: str                      # "polymarket", "sports", "defi", "options"
    direction: Direction
    instruments: list[Instrument]
    constraint_violated: ConstraintKind
    price_sum: float
    raw_profit: float                # before fees
    net_profit: float                # after fees
    description: str = ""
    timestamp: Optional[datetime] = None

    @property
    def is_profitable(self) -> bool:
        return self.net_profit > 0
