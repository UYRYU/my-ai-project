"""Polymarket Gamma API client.

The Gamma API (gamma-api.polymarket.com) provides market discovery and metadata.
No authentication is required for read-only access.

Hierarchy:
  GET /events  -> Event objects (each containing nested markets)
  GET /markets -> Market objects with token prices
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional

import httpx

from polymarket_arbitrage.config import (
    DEFAULT_FETCH_LIMIT,
    GAMMA_EVENTS_ENDPOINT,
    GAMMA_MARKETS_ENDPOINT,
)
from polymarket_arbitrage.models.market import Event, Market, MarketStatus, Token

logger = logging.getLogger(__name__)


def _parse_datetime(val: Any) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    try:
        # Handle ISO 8601 strings from the API
        return datetime.fromisoformat(str(val).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _parse_token(data: dict[str, Any]) -> Token:
    return Token(
        token_id=str(data.get("token_id", "")),
        outcome=str(data.get("outcome", "")),
        price=float(data.get("price", 0.0)),
        winner=data.get("winner"),
    )


def _parse_market(data: dict[str, Any]) -> Market:
    tokens = []
    for tok in data.get("tokens", []) or []:
        tokens.append(_parse_token(tok))

    # If no structured tokens, build from outcomePrices / clobTokenIds
    if not tokens and data.get("outcomePrices"):
        try:
            prices = data["outcomePrices"]
            if isinstance(prices, str):
                import json
                prices = json.loads(prices)
            clob_ids = data.get("clobTokenIds", [])
            if isinstance(clob_ids, str):
                import json
                clob_ids = json.loads(clob_ids)
            outcomes = ["Yes", "No"]
            for i, price in enumerate(prices):
                tokens.append(Token(
                    token_id=str(clob_ids[i]) if i < len(clob_ids) else "",
                    outcome=outcomes[i] if i < len(outcomes) else f"Outcome_{i}",
                    price=float(price),
                ))
        except (ValueError, TypeError, KeyError):
            pass

    return Market(
        id=str(data.get("id", "")),
        question=str(data.get("question", "")),
        condition_id=str(data.get("conditionId", data.get("condition_id", ""))),
        slug=str(data.get("slug", "")),
        tokens=tokens,
        status=MarketStatus(data.get("active", True) and "active" or "closed"),
        volume=float(data.get("volume", 0) or 0),
        liquidity=float(data.get("liquidity", 0) or 0),
        start_date=_parse_datetime(data.get("startDate")),
        end_date=_parse_datetime(data.get("endDate")),
        description=str(data.get("description", "")),
    )


def _parse_event(data: dict[str, Any]) -> Event:
    markets = []
    for m in data.get("markets", []) or []:
        markets.append(_parse_market(m))
    return Event(
        id=str(data.get("id", "")),
        title=str(data.get("title", "")),
        slug=str(data.get("slug", "")),
        markets=markets,
        neg_risk=bool(data.get("negRisk", False)),
        description=str(data.get("description", "")),
    )


class GammaClient:
    """Async client for the Polymarket Gamma API."""

    def __init__(self, timeout: float = 30.0) -> None:
        self._client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> GammaClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def _get_json(self, url: str, params: dict[str, Any]) -> Any:
        resp = await self._client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------
    async def fetch_events(
        self,
        *,
        limit: int = DEFAULT_FETCH_LIMIT,
        offset: int = 0,
        active: Optional[bool] = None,
        closed: Optional[bool] = None,
        slug: Optional[str] = None,
    ) -> list[Event]:
        """Fetch events from the Gamma API."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if active is not None:
            params["active"] = str(active).lower()
        if closed is not None:
            params["closed"] = str(closed).lower()
        if slug:
            params["slug"] = slug
        data = await self._get_json(GAMMA_EVENTS_ENDPOINT, params)
        if isinstance(data, list):
            return [_parse_event(e) for e in data]
        return []

    async def fetch_all_events(
        self,
        *,
        active: Optional[bool] = None,
        closed: Optional[bool] = None,
        batch_size: int = DEFAULT_FETCH_LIMIT,
        max_events: Optional[int] = None,
    ) -> list[Event]:
        """Paginate through all events."""
        all_events: list[Event] = []
        offset = 0
        while True:
            batch = await self.fetch_events(
                limit=batch_size, offset=offset, active=active, closed=closed,
            )
            if not batch:
                break
            all_events.extend(batch)
            logger.info("Fetched %d events (total: %d)", len(batch), len(all_events))
            if max_events and len(all_events) >= max_events:
                all_events = all_events[:max_events]
                break
            if len(batch) < batch_size:
                break
            offset += batch_size
            await asyncio.sleep(0.1)  # respect rate limits
        return all_events

    # ------------------------------------------------------------------
    # Markets
    # ------------------------------------------------------------------
    async def fetch_markets(
        self,
        *,
        limit: int = DEFAULT_FETCH_LIMIT,
        offset: int = 0,
        active: Optional[bool] = None,
    ) -> list[Market]:
        """Fetch markets from the Gamma API."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if active is not None:
            params["active"] = str(active).lower()
        data = await self._get_json(GAMMA_MARKETS_ENDPOINT, params)
        if isinstance(data, list):
            return [_parse_market(m) for m in data]
        return []


def fetch_events_sync(**kwargs: Any) -> list[Event]:
    """Synchronous convenience wrapper."""
    async def _run() -> list[Event]:
        async with GammaClient() as client:
            return await client.fetch_all_events(**kwargs)
    return asyncio.run(_run())
