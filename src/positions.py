"""In-memory position and PnL tracker.

Persists nothing across restarts — wire to a file/DB before going live
with real money. Sufficient for paper trading and circuit-breaker logic.
"""

from dataclasses import dataclass, field
from threading import Lock


@dataclass
class Position:
    token_id: str
    shares: float = 0.0
    cost_basis: float = 0.0  # USD spent

    def add(self, shares: float, price: float) -> None:
        self.shares += shares
        self.cost_basis += shares * price


@dataclass
class Book:
    positions: dict[str, Position] = field(default_factory=dict)
    realized_pnl: float = 0.0
    fills_today: int = 0
    _lock: Lock = field(default_factory=Lock, repr=False)

    def record_fill(self, token_id: str, shares: float, price: float) -> None:
        with self._lock:
            pos = self.positions.setdefault(token_id, Position(token_id=token_id))
            pos.add(shares, price)
            self.fills_today += 1

    def settle(self, token_id: str, payout_per_share: float) -> float:
        """Mark a market as resolved. Returns realized PnL on this leg."""
        with self._lock:
            pos = self.positions.pop(token_id, None)
            if pos is None:
                return 0.0
            proceeds = pos.shares * payout_per_share
            pnl = proceeds - pos.cost_basis
            self.realized_pnl += pnl
            return pnl

    def gross_exposure_usd(self) -> float:
        with self._lock:
            return sum(p.cost_basis for p in self.positions.values())
