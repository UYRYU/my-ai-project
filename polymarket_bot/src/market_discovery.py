"""Discover and fetch active BTC short-term markets from Polymarket CLOB API."""

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
    """Fetches active markets and order books from Polymarket CLOB API."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.base_url = config.api_base.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(15.0),
                headers={"Accept": "application/json"},
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def fetch_markets(self, next_cursor: str = "") -> tuple[list[dict], str]:
        """Fetch markets from CLOB API /markets endpoint.

        Returns (markets_list, next_cursor).
        """
        client = await self._get_client()
        params: dict = {"active": "true"}
        if next_cursor:
            params["next_cursor"] = next_cursor

        try:
            resp = await client.get("/markets", params=params)
            resp.raise_for_status()
            data = resp.json()
            # CLOB API returns {"data": [...], "next_cursor": "..."}
            markets = data if isinstance(data, list) else data.get("data", data)
            cursor = data.get("next_cursor", "") if isinstance(data, dict) else ""
            return markets, cursor
        except httpx.HTTPStatusError as e:
            logger.error("HTTP error fetching markets: %s", e)
            return [], ""
        except Exception as e:
            logger.error("Error fetching markets: %s", e)
            return [], ""

    async def fetch_all_btc_short_term_markets(self) -> list[Market]:
        """Paginate through all markets, filter for BTC short-term ones."""
        all_markets: list[Market] = []
        cursor = ""
        page = 0
        max_pages = 20  # Safety limit

        while page < max_pages:
            raw_markets, cursor = await self.fetch_markets(cursor)
            if not raw_markets:
                break

            for m in raw_markets:
                market = self._parse_market(m)
                if market and self._is_btc_short_term(market):
                    all_markets.append(market)

            page += 1
            if not cursor or cursor == "LTE":
                break

        logger.info("Found %d BTC short-term markets", len(all_markets))
        return all_markets

    async def fetch_order_book(self, token_id: str) -> OrderBookSnapshot:
        """Fetch order book for a specific token."""
        client = await self._get_client()
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

    def _parse_market(self, raw: dict) -> Optional[Market]:
        """Parse raw API response into Market model."""
        try:
            tokens_raw = raw.get("tokens", [])
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
                volume=float(raw.get("volume", 0)),
            )
        except Exception as e:
            logger.debug("Failed to parse market: %s", e)
            return None

    def _parse_order_book(self, data: dict) -> OrderBookSnapshot:
        """Parse order book response."""
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
