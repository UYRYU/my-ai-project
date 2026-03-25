"""Discover and fetch active markets from Polymarket CLOB API.

Scans ALL active markets for mispricing opportunities.
No keyword filtering — any market with YES+NO ask sum deviating from 1.0 is a candidate.
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


class MarketDiscovery:
    """Fetches active markets and order books from Polymarket CLOB API."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.clob_url = config.clob_api.rstrip("/")
        self._clob_client: Optional[httpx.AsyncClient] = None

    # ── HTTP client ──

    async def _get_clob_client(self) -> httpx.AsyncClient:
        if self._clob_client is None or self._clob_client.is_closed:
            self._clob_client = httpx.AsyncClient(
                base_url=self.clob_url,
                timeout=httpx.Timeout(15.0),
                headers={"Accept": "application/json"},
            )
        return self._clob_client

    async def close(self) -> None:
        if self._clob_client and not self._clob_client.is_closed:
            await self._clob_client.aclose()

    # ── CLOB API: /markets (cursor-paginated) ──

    async def fetch_clob_markets(
        self, next_cursor: str = "MA==",
    ) -> tuple[list[dict], str]:
        """Fetch one page of markets from CLOB API.

        Returns (markets_list, next_cursor). Cursor "LTE" means no more pages.
        """
        client = await self._get_clob_client()
        params: dict[str, str] = {"next_cursor": next_cursor}
        try:
            resp = await client.get("/markets", params=params)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict):
                return data.get("data", []), data.get("next_cursor", "LTE")
            return data, "LTE"
        except httpx.HTTPStatusError as e:
            logger.warning("CLOB /markets HTTP %s", e.response.status_code)
            return [], "LTE"
        except Exception as e:
            logger.warning("CLOB /markets error: %s", e)
            return [], "LTE"

    # ── Fetch all active markets ──

    async def fetch_active_markets(self, max_pages: int = 50) -> list[Market]:
        """Fetch all active markets from CLOB API and return ones with valid tokens."""
        all_markets: list[Market] = []
        seen: set[str] = set()
        cursor = "MA=="

        for _ in range(max_pages):
            raw_list, cursor = await self.fetch_clob_markets(cursor)
            if not raw_list:
                break

            for m in raw_list:
                market = self._parse_market(m)
                if not market or not market.condition_id:
                    continue
                if market.condition_id in seen:
                    continue
                seen.add(market.condition_id)

                # Skip closed or inactive
                if not market.active:
                    continue

                # Must have at least 2 tokens (YES/NO)
                if len(market.tokens) < 2:
                    continue

                # Skip expired markets
                if market.end_date:
                    try:
                        end_dt = datetime.fromisoformat(
                            market.end_date.replace("Z", "+00:00")
                        )
                        if end_dt < datetime.now(timezone.utc):
                            continue
                    except (ValueError, TypeError):
                        pass

                all_markets.append(market)

            if not cursor or cursor == "LTE":
                break

        logger.info("CLOB API: found %d active markets", len(all_markets))
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
            if token.token_id:
                token.order_book = await self.fetch_order_book(token.token_id)
        return market

    # ── Parsing helpers ──

    def _parse_market(self, raw: dict) -> Optional[Market]:
        """Parse a raw CLOB API market dict into a Market model."""
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
                active=bool(raw.get("active", True)),
                end_date=raw.get("end_date_iso", raw.get("end_date", "")),
                volume=float(raw.get("volume", 0) or 0),
            )
        except Exception as e:
            logger.debug("Failed to parse market: %s", e)
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
