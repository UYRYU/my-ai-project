"""Discover and fetch active BTC short-term markets from Polymarket APIs.

Two data sources (tried in order):
1. Gamma API (gamma-api.polymarket.com/events) — richest data, but may 403
2. CLOB API  (clob.polymarket.com/markets)      — always available, cursor-paginated
Order books always come from CLOB API /book.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from .config import Config
from .models import Market, MarketToken, OrderBookLevel, OrderBookSnapshot

logger = logging.getLogger("polymarket_bot")

# Keywords to identify BTC-related markets
BTC_KEYWORDS = ["btc", "bitcoin"]
# Maximum days until end_date to qualify as "short-term"
SHORT_TERM_MAX_DAYS = 30


class MarketDiscovery:
    """Fetches active markets and order books from Polymarket APIs."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.gamma_url = config.gamma_api.rstrip("/")
        self.clob_url = config.clob_api.rstrip("/")
        self._gamma_client: Optional[httpx.AsyncClient] = None
        self._clob_client: Optional[httpx.AsyncClient] = None

    # ── HTTP clients ──

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

    # ── Gamma API: /events ──

    async def fetch_events(self, offset: int = 0, limit: int = 100) -> list[dict]:
        """Fetch active events from Gamma API /events.

        Returns raw event dicts, each containing a "markets" list.
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
            logger.warning("Gamma API /events HTTP %s", e.response.status_code)
            return []
        except Exception as e:
            logger.warning("Gamma API /events error: %s", e)
            return []

    # ── CLOB API: /markets (cursor-paginated) ──

    async def fetch_clob_markets(
        self, next_cursor: str = "MA==", *, active: bool = False,
    ) -> tuple[list[dict], str]:
        """Fetch one page of markets from CLOB API.

        Returns (markets_list, next_cursor).  Cursor "LTE" means no more pages.
        """
        client = await self._get_clob_client()
        params: dict[str, str] = {"next_cursor": next_cursor}
        if active:
            params["active"] = "true"
            params["closed"] = "false"
        try:
            resp = await client.get("/markets", params=params)
            resp.raise_for_status()
            data = resp.json()
            # CLOB /markets -> {"data": [...], "next_cursor": "..."}
            if isinstance(data, dict):
                return data.get("data", []), data.get("next_cursor", "LTE")
            return data, "LTE"
        except httpx.HTTPStatusError as e:
            logger.warning("CLOB /markets HTTP %s", e.response.status_code)
            return [], "LTE"
        except Exception as e:
            logger.warning("CLOB /markets error: %s", e)
            return [], "LTE"

    # ── Unified market discovery ──

    async def fetch_all_btc_short_term_markets(self) -> list[Market]:
        """Try Gamma API first; fall back to CLOB API if Gamma fails."""
        markets = await self._fetch_via_gamma()
        if markets:
            return markets

        logger.info("Gamma API returned 0 results, falling back to CLOB API /markets")
        return await self._fetch_via_clob()

    async def _fetch_via_gamma(self) -> list[Market]:
        """Paginate Gamma /events and filter for BTC short-term markets."""
        all_markets: list[Market] = []
        offset = 0
        limit = 100

        for _ in range(20):
            events = await self.fetch_events(offset=offset, limit=limit)
            if not events:
                break
            for event in events:
                for m in event.get("markets", []):
                    market = self._parse_market(m, source="gamma")
                    if market and self._is_btc_short_term(market):
                        all_markets.append(market)
            if len(events) < limit:
                break
            offset += limit

        if all_markets:
            logger.info("Gamma API: found %d BTC short-term markets", len(all_markets))
        return all_markets

    async def _fetch_via_clob(self) -> list[Market]:
        """Paginate CLOB /markets and filter for BTC short-term markets."""
        all_markets: list[Market] = []
        cursor = "MA=="

        for _ in range(50):  # CLOB pages can be small
            raw_list, cursor = await self.fetch_clob_markets(cursor, active=True)
            if not raw_list:
                break
            for m in raw_list:
                market = self._parse_market(m, source="clob")
                if market and self._is_btc_short_term(market):
                    all_markets.append(market)
            if not cursor or cursor == "LTE":
                break

        logger.info("CLOB API: found %d BTC short-term markets", len(all_markets))
        return all_markets

    # ── CLOB API: /book ──

    async def fetch_order_book(self, token_id: str) -> OrderBookSnapshot:
        """Fetch order book for a specific token from CLOB API /book."""
        client = await self._get_clob_client()
        try:
            resp = await client.get("/book", params={"token_id": token_id})
            resp.raise_for_status()
            data = resp.json()
            return self._parse_order_book(data)
        except httpx.HTTPStatusError as e:
            logger.warning("CLOB /book HTTP %s for %s", e.response.status_code, token_id[:16])
            return OrderBookSnapshot()
        except Exception as e:
            logger.warning("CLOB /book error for %s: %s", token_id[:16], e)
            return OrderBookSnapshot()

    async def enrich_market_with_books(self, market: Market) -> Market:
        """Fetch order books for all tokens in a market."""
        for token in market.tokens:
            token.order_book = await self.fetch_order_book(token.token_id)
        return market

    # ── Parsing helpers ──

    def _parse_market(self, raw: dict, source: str = "gamma") -> Optional[Market]:
        """Parse a raw API market dict into a Market model.

        Works for both Gamma and CLOB response shapes.
        """
        try:
            tokens_raw = raw.get("tokens", [])
            if isinstance(tokens_raw, str):
                tokens_raw = json.loads(tokens_raw)

            tokens = []
            for t in tokens_raw:
                tokens.append(
                    MarketToken(
                        token_id=t.get("token_id", ""),
                        outcome=t.get("outcome", ""),
                        price=float(t.get("price", 0) or 0),
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
            logger.debug("Failed to parse market (%s): %s", source, e)
            return None

    def _parse_order_book(self, data: dict) -> OrderBookSnapshot:
        """Parse CLOB /book response."""
        bids = []
        asks = []
        for b in data.get("bids", []):
            bids.append(OrderBookLevel(price=float(b.get("price", 0)), size=float(b.get("size", 0))))
        for a in data.get("asks", []):
            asks.append(OrderBookLevel(price=float(a.get("price", 0)), size=float(a.get("size", 0))))
        bids.sort(key=lambda x: x.price, reverse=True)
        asks.sort(key=lambda x: x.price)
        return OrderBookSnapshot(bids=bids, asks=asks)

    @staticmethod
    def _is_btc_short_term(market: Market) -> bool:
        """Check if market is BTC-related and short-term (ends within 30 days)."""
        q = market.question.lower()
        has_btc = any(kw in q for kw in BTC_KEYWORDS)
        if not has_btc:
            return False

        # If no end_date, accept all BTC markets
        if not market.end_date:
            return True

        # Parse end_date and check if within SHORT_TERM_MAX_DAYS
        try:
            end_dt = datetime.fromisoformat(market.end_date.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            days_left = (end_dt - now).days
            return 0 <= days_left <= SHORT_TERM_MAX_DAYS
        except (ValueError, TypeError):
            # If date parsing fails, include it anyway
            return True
