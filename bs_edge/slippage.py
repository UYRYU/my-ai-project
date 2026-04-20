"""Slippage models for simulating fills against a Polymarket-style CLOB.

Polymarket books are thin on short-dated BTC Up/Down markets. A constant
half-spread understates cost for any non-trivial stake. The models here
let the backtester swap in increasingly realistic fill logic without
changing engine code:

* ``ConstantSpread`` -- the original behaviour: buy at mid + h, sell at
  mid - h. Cheap, reasonable for small size.
* ``LinearImpact`` -- adds an impact proportional to notional in dollars.
  Good first-order approximation when the book is roughly flat on top.
* ``SqrtImpact`` -- impact scales with sqrt(notional), matching the
  empirical Kyle-like behaviour seen in thicker venues.
* ``BookWalkSlippage`` -- if orderbook snapshots are available (keyed by
  timestamp), we walk price levels to compute the true average fill.

All models clip fills to the [0, 1] probability range since Polymarket
prices cannot leave that interval.
"""

from __future__ import annotations

import bisect
import logging
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

import pandas as pd

logger = logging.getLogger(__name__)


class SlippageModel(ABC):
    """Compute realised fill prices on a [0,1] binary book."""

    @abstractmethod
    def buy_price(self, mid: float, notional: float, ts: int | None = None) -> float: ...

    @abstractmethod
    def sell_price(self, mid: float, notional: float, ts: int | None = None) -> float: ...


# ---------------------------------------------------------------------------
# Simple closed-form models
# ---------------------------------------------------------------------------


@dataclass
class ConstantSpread(SlippageModel):
    half_spread: float = 0.01

    def buy_price(self, mid: float, notional: float, ts: int | None = None) -> float:
        return _clip(mid + self.half_spread)

    def sell_price(self, mid: float, notional: float, ts: int | None = None) -> float:
        return _clip(mid - self.half_spread)


@dataclass
class LinearImpact(SlippageModel):
    """``price = mid +/- (half_spread + impact_per_dollar * notional)``."""

    half_spread: float = 0.005
    impact_per_dollar: float = 1e-5  # 1bp of probability per $1000 notional

    def buy_price(self, mid: float, notional: float, ts: int | None = None) -> float:
        return _clip(mid + self.half_spread + self.impact_per_dollar * max(notional, 0.0))

    def sell_price(self, mid: float, notional: float, ts: int | None = None) -> float:
        return _clip(mid - self.half_spread - self.impact_per_dollar * max(notional, 0.0))


@dataclass
class SqrtImpact(SlippageModel):
    """``price = mid +/- (half_spread + k * sqrt(notional))``."""

    half_spread: float = 0.005
    k: float = 2e-4

    def buy_price(self, mid: float, notional: float, ts: int | None = None) -> float:
        return _clip(mid + self.half_spread + self.k * math.sqrt(max(notional, 0.0)))

    def sell_price(self, mid: float, notional: float, ts: int | None = None) -> float:
        return _clip(mid - self.half_spread - self.k * math.sqrt(max(notional, 0.0)))


# ---------------------------------------------------------------------------
# Book-walking model (when real snapshots are available)
# ---------------------------------------------------------------------------


@dataclass
class BookSnapshot:
    """Orderbook at a point in time. Bids sorted descending, asks ascending."""

    bids: Sequence[tuple[float, float]]  # (price, size_in_contracts)
    asks: Sequence[tuple[float, float]]


class BookWalkSlippage(SlippageModel):
    """Walk a time-indexed snapshot store to compute average fill price.

    ``snapshot_fn(ts)`` returns the most recent ``BookSnapshot`` at or
    before ``ts``. If no snapshot exists we fall back to ``fallback``.
    """

    def __init__(
        self,
        snapshot_fn: Callable[[int], BookSnapshot | None],
        fallback: SlippageModel | None = None,
    ) -> None:
        self._snap = snapshot_fn
        self._fallback = fallback or ConstantSpread()

    def buy_price(self, mid: float, notional: float, ts: int | None = None) -> float:
        snap = self._snap(ts) if ts is not None else None
        if snap is None or not snap.asks:
            return self._fallback.buy_price(mid, notional, ts)
        return _walk(snap.asks, notional, side="buy")

    def sell_price(self, mid: float, notional: float, ts: int | None = None) -> float:
        snap = self._snap(ts) if ts is not None else None
        if snap is None or not snap.bids:
            return self._fallback.sell_price(mid, notional, ts)
        return _walk(snap.bids, notional, side="sell")


class SnapshotStore:
    """Timestamp-indexed cache of ``BookSnapshot`` objects.

    Uses bisect-on-sorted-keys for O(log n) lookup. Primarily a helper
    for historical replays where snapshots were recorded out-of-band.
    """

    def __init__(self, snapshots: Mapping[int, BookSnapshot] | None = None) -> None:
        self._times: list[int] = []
        self._snaps: list[BookSnapshot] = []
        if snapshots:
            for ts in sorted(snapshots):
                self._times.append(int(ts))
                self._snaps.append(snapshots[ts])

    def add(self, ts: int, snap: BookSnapshot) -> None:
        idx = bisect.bisect_right(self._times, ts)
        self._times.insert(idx, ts)
        self._snaps.insert(idx, snap)

    def at(self, ts: int) -> BookSnapshot | None:
        if not self._times:
            return None
        idx = bisect.bisect_right(self._times, ts) - 1
        return self._snaps[idx] if idx >= 0 else None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clip(price: float) -> float:
    return max(0.0, min(1.0, price))


def _walk(levels: Sequence[tuple[float, float]], notional: float, side: str) -> float:
    """Walk through price levels until ``notional`` is filled.

    ``levels`` are (price, size_in_contracts). For a Polymarket-style
    book, price is in [0,1] and "contracts" settle to $1. Notional
    consumed at each level = price * size.
    """
    if notional <= 0.0 or not levels:
        return _clip(levels[0][0]) if levels else 0.0
    remaining = notional
    cost = 0.0
    filled_qty = 0.0
    for price, size in levels:
        level_notional = price * size
        take = min(remaining, level_notional)
        if price > 0:
            take_qty = take / price
        else:
            take_qty = size if side == "sell" else 0.0
        cost += take_qty * price
        filled_qty += take_qty
        remaining -= take
        if remaining <= 1e-9:
            break
    if filled_qty <= 0:
        return _clip(levels[0][0])
    # If the book couldn't fully fill, the remainder is an implicit
    # penalty: cap price at the last level walked.
    return _clip(cost / filled_qty)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_from_config(cfg) -> SlippageModel:
    """Construct a SlippageModel from the bs_edge Config object."""
    name = (cfg.slippage_model or "constant").lower()
    if name == "constant":
        return ConstantSpread(half_spread=cfg.half_spread)
    if name == "linear":
        return LinearImpact(
            half_spread=cfg.half_spread,
            impact_per_dollar=cfg.impact_per_dollar,
        )
    if name == "sqrt":
        return SqrtImpact(half_spread=cfg.half_spread, k=cfg.impact_sqrt_k)
    raise ValueError(f"unknown slippage_model {name!r}")
