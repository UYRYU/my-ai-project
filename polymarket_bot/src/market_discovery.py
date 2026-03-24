"""Discover and fetch active BTC short-term markets from Polymarket APIs.

- Gamma API (gamma-api.polymarket.com): market/event discovery
- CLOB API (clob.polymarket.com): order book data
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from .config import Config
from .models import Market, MarketToken, OrderBookLevel, OrderBookSnapshot

logger = logging.getLogger("polymarket_bot")

# Keywords to identify BTC short-term markets
BTC_KEYWORDS = ["btc", "bitcoin"]
SHORT_TERM_KEYWORDS = ["5-minute", "5 minute", "5min", "1-minute", "1 minute", "1min", "short"]


class MarketDiscovery:
    """Fetches active markets from Gamma API, order books from CLOB API."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.gamma_url = config.gamma_api.rstrip("/")
        self.clob_url = config.clob_api.rstrip("/")
        self._gamma_client: Optional[httpx.AsyncClient] = None
        self._clob_client: Optional[httpx.AsyncClient] = None

    async def _get_gamma_client(self) -> httpx.AsyncClient:
        if self._gamma_client is None or self._gamma_client.is_closed:
            self._gamma_client = httpx.AsyncClient(
                base_url=self.gamma_url,
                timeout=httpx.Timeout(15.0),
                headers={"Accept": "application/json"},
            )
        return self._gamma_client

    async def _get_clob_client(self) -> httpx.AsyncClient:
        if self._clob_client is None or self._clob_client.is_closed:
            self._clob_client = httpx.AsyncClient(
                base_url=self.clob_url,
                timeout=httpx.Timeout(15.0),
                headers={"Accept": "application/json"},
            )
        return self._clob_client

    async def close(self) -> None:
        for client in (self._gamma_client, self._clob_client):
            if client and not client.is_closed:
                await client.aclose()

    async def fetch_events(self, offset: int = 0, limit: int = 100) -> list[dict]:
        """Fetch active events from Gamma API /events endpoint.

        Events contain their associated markets, so this is the most
        efficient way to discover all active markets (per Polymarket docs).
        """
        client = await self._get_gamma_client()
        params = {
            "active": "true",
            "closed": "false",
            "limit": str(limit),
            "offset": str(offset),
            "order": "volume_24hr",
            "ascending": "false",
        }

        try:
            resp = await client.get("/events", params=params)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []
        except httpx.HTTPStatusError as e:
            logger.error("HTTP error fetching events: %s", e)
            return []
        except Exception as e:
            logger.error("Error fetching events: %s", e)
            return []

    async def fetch_all_btc_short_term_markets(self) -> list[Market]:
        """Paginate through Gamma API events, filter for BTC short-term markets."""
        all_markets: list[Market] = []
        offset = 0
        limit = 100
        max_pages = 20  # Safety limit

        for page in range(max_pages):
            events = await self.fetch_events(offset=offset, limit=limit)
            if not events:
                break

            for event in events:
                # Each event can contain multiple markets
                event_markets = event.get("markets", [])
                for m in event_markets:
                    market = self._parse_gamma_market(m)
                    if market and self._is_btc_short_term(market):
                        all_markets.append(market)

            # If we got fewer results than limit, we've reached the end
            if len(events) < limit:
                break
            offset += limit

        logger.info("Found %d BTC short-term markets", len(all_markets))
        return all_markets

    async def fetch_order_book(self, token_id: str) -> OrderBookSnapshot:
        """Fetch order book for a specific token from CLOB API."""
        client = await self._get_clob_client()
        try:
            resp = await client.get("/book", params={"token_id": token_id})
            resp.raise_for_status()
            data = resp.json()
            return self._parse_order_book(data)
        except httpx.HTTPStatusError as e:
            logger.warning("HTTP error fetching order book for %s: %s", token_id, e)
            return OrderBookSnapshot()
        except Exception as e:
            logger.warning("Error fetching order book for %s: %s", token_id, e)
            return OrderBookSnapshot()

    async def enrich_market_with_books(self, market: Market) -> Market:
        """Fetch order books for all tokens in a market."""
        for token in market.tokens:
            token.order_book = await self.fetch_order_book(token.token_id)
        return market

    def _parse_gamma_market(self, raw: dict) -> Optional[Market]:
        """Parse Gamma API market response into Market model.

        Gamma API market fields:
        - condition_id, question, slug, active, end_date_iso
        - tokens: [{token_id, outcome, price}, ...]
        - volume, volume_24hr
        """
        try:
            tokens_raw = raw.get("tokens", [])
            if isinstance(tokens_raw, str):
                # Some responses return tokens as JSON string
                import json
                tokens_raw = json.loads(tokens_raw)

            tokens = []
            for t in tokens_raw:
                tokens.append(
                    MarketToken(
                        token_id=t.get("token_id", ""),
                        outcome=t.get("outcome", ""),
                        price=float(t.get("price", 0)),
                    )
                )

            return Market(
                condition_id=raw.get("condition_id", ""),
                question=raw.get("question", ""),
                slug=raw.get("market_slug", raw.get("slug", "")),
                tokens=tokens,
                active=raw.get("active", True),
                end_date=raw.get("end_date_iso", raw.get("end_date", "")),
                volume=float(raw.get("volume", 0) or 0),
            )
        except Exception as e:
            logger.debug("Failed to parse market: %s", e)
            return None

    def _parse_order_book(self, data: dict) -> OrderBookSnapshot:
        """Parse CLOB API order book response."""
        bids = []
        asks = []
        for b in data.get("bids", []):
            bids.append(OrderBookLevel(price=float(b.get("price", 0)), size=float(b.get("size", 0))))
        for a in data.get("asks", []):
            asks.append(OrderBookLevel(price=float(a.get("price", 0)), size=float(a.get("size", 0))))
        # Sort: bids descending, asks ascending
        bids.sort(key=lambda x: x.price, reverse=True)
        asks.sort(key=lambda x: x.price)
        return OrderBookSnapshot(bids=bids, asks=asks)

    @staticmethod
    def _is_btc_short_term(market: Market) -> bool:
        """Check if market is BTC-related and short-term."""
        q = market.question.lower()
        has_btc = any(kw in q for kw in BTC_KEYWORDS)
        has_short = any(kw in q for kw in SHORT_TERM_KEYWORDS)
        return has_btc and has_short
