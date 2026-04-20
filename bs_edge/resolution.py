"""Outcome resolution sources for backtesting.

Polymarket Up/Down markets are resolved by an oracle (UMA / automatic)
against a named price source -- typically Coinbase or a reference index
quoted in the event's ``resolutionSource`` field. Using Binance spot at
``close_ts`` as a proxy is close but not identical and will bias the
backtest when the two prints diverge (index lag, outlier trades).

Resolvers here produce a realised outcome ``"UP"`` or ``"DOWN"`` for a
given market. The caller composes them in priority order; typical setup::

    PolymarketNativeResolver(client)  # use the oracle's verdict
    BinanceCloseResolver(btc_bars)    # fallback when not yet resolved

``backtest_market`` accepts a single resolver or a ``ChainedResolver``.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Iterable

import pandas as pd

from .market_loader import UpDownMarket
from .polymarket_client import PolymarketClient

logger = logging.getLogger(__name__)


class OutcomeResolver(ABC):
    @abstractmethod
    def resolve(self, market: UpDownMarket) -> str | None:  # "UP" | "DOWN" | None
        ...


class PolymarketNativeResolver(OutcomeResolver):
    """Use Polymarket's own resolved outcome, when available.

    We prefer ``resolved_outcome`` already parsed on the market record;
    if absent we re-fetch the market to pick up a late resolution.
    """

    def __init__(self, client: PolymarketClient | None = None) -> None:
        self._client = client

    def resolve(self, market: UpDownMarket) -> str | None:
        if market.resolved_outcome:
            return market.resolved_outcome
        if not market.resolved and self._client is None:
            return None
        if self._client is None:
            return None
        try:
            raw = self._client.get_market(market.condition_id)
        except Exception as exc:
            logger.warning("native resolve failed for %s: %s", market.slug, exc)
            return None
        # Import locally to avoid a circular import at module load.
        from .market_loader import _extract_resolved_outcome, _parse_string_array

        outcomes = _parse_string_array(raw.get("outcomes"))
        prices = _parse_string_array(raw.get("outcomePrices"))
        return _extract_resolved_outcome(outcomes, prices)


class BinanceCloseResolver(OutcomeResolver):
    """Derive outcome from the BTC close at/after the market's close_ts."""

    def __init__(self, btc_bars: pd.DataFrame) -> None:
        self._bars = btc_bars

    def resolve(self, market: UpDownMarket) -> str | None:
        if market.reference_price is None or self._bars.empty:
            return None
        ts = pd.Timestamp(market.close_ts, unit="s", tz="UTC")
        after = self._bars.loc[ts:]
        if after.empty:
            return None
        settle = float(after["close"].iloc[0])
        return "UP" if settle > market.reference_price else "DOWN"


class ChainedResolver(OutcomeResolver):
    """Try each resolver in turn and return the first non-None answer."""

    def __init__(self, resolvers: Iterable[OutcomeResolver]) -> None:
        self._resolvers = list(resolvers)

    def resolve(self, market: UpDownMarket) -> str | None:
        for r in self._resolvers:
            out = r.resolve(market)
            if out is not None:
                return out
        return None
