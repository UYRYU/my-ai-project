"""WebSocket client for real-time order book updates from Polymarket."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any, Optional

import websockets
from websockets.exceptions import ConnectionClosed

from .config import Config
from .models import OrderBookLevel, OrderBookSnapshot

logger = logging.getLogger("polymarket_bot")


class PolymarketWebSocket:
    """Manages WebSocket connection to Polymarket for live order book updates."""

    def __init__(
        self,
        config: Config,
        on_book_update: Optional[Callable[[str, OrderBookSnapshot], Any]] = None,
    ) -> None:
        self.config = config
        self.ws_url = config.ws_url
        self.on_book_update = on_book_update
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._subscribed_tokens: set[str] = set()
        self._running = False
        self._reconnect_count = 0

    async def connect(self) -> None:
        """Connect to the WebSocket server with auto-reconnect."""
        self._running = True
        while self._running and self._reconnect_count < self.config.ws_max_reconnect_attempts:
            try:
                logger.info("Connecting to WebSocket: %s", self.ws_url)
                async with websockets.connect(
                    self.ws_url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    self._ws = ws
                    self._reconnect_count = 0
                    logger.info("WebSocket connected")

                    # Resubscribe to tokens
                    if self._subscribed_tokens:
                        await self._send_subscribe(list(self._subscribed_tokens))

                    await self._listen(ws)

            except ConnectionClosed as e:
                logger.warning("WebSocket connection closed: %s", e)
            except Exception as e:
                logger.error("WebSocket error: %s", e)

            if self._running:
                self._reconnect_count += 1
                delay = self.config.ws_reconnect_delay_sec * self._reconnect_count
                logger.info(
                    "Reconnecting in %ds (attempt %d/%d)",
                    delay,
                    self._reconnect_count,
                    self.config.ws_max_reconnect_attempts,
                )
                await asyncio.sleep(delay)

        if self._reconnect_count >= self.config.ws_max_reconnect_attempts:
            logger.error("Max reconnect attempts reached, giving up")

    async def _listen(self, ws: websockets.WebSocketClientProtocol) -> None:
        """Listen for incoming messages."""
        async for message in ws:
            try:
                data = json.loads(message)
                await self._handle_message(data)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON received: %s", message[:200])
            except Exception as e:
                logger.error("Error handling WS message: %s", e)

    async def _handle_message(self, data: dict | list) -> None:
        """Process a WebSocket message (book update)."""
        # Polymarket WS sends updates in various formats
        # Common format: {"market": token_id, "bids": [...], "asks": [...]}
        # Or array of updates
        if isinstance(data, list):
            for item in data:
                await self._handle_single_update(item)
        else:
            await self._handle_single_update(data)

    async def _handle_single_update(self, data: dict) -> None:
        """Handle a single book update message."""
        asset_id = data.get("asset_id", data.get("market", ""))
        if not asset_id:
            return

        # Parse book snapshot from update
        book = self._parse_book_update(data)
        if self.on_book_update:
            try:
                result = self.on_book_update(asset_id, book)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error("Error in book update callback: %s", e)

    def _parse_book_update(self, data: dict) -> OrderBookSnapshot:
        """Parse WS book update into OrderBookSnapshot."""
        bids = []
        asks = []
        for b in data.get("bids", []):
            bids.append(
                OrderBookLevel(
                    price=float(b.get("price", 0)),
                    size=float(b.get("size", 0)),
                )
            )
        for a in data.get("asks", []):
            asks.append(
                OrderBookLevel(
                    price=float(a.get("price", 0)),
                    size=float(a.get("size", 0)),
                )
            )
        bids.sort(key=lambda x: x.price, reverse=True)
        asks.sort(key=lambda x: x.price)
        return OrderBookSnapshot(bids=bids, asks=asks)

    async def subscribe(self, token_ids: list[str]) -> None:
        """Subscribe to order book updates for given tokens."""
        new_tokens = [t for t in token_ids if t not in self._subscribed_tokens]
        if not new_tokens:
            return
        self._subscribed_tokens.update(new_tokens)
        if self._ws:
            await self._send_subscribe(new_tokens)

    async def _send_subscribe(self, token_ids: list[str]) -> None:
        """Send subscription message to WS."""
        if not self._ws:
            return
        # Polymarket CLOB WS subscription format
        for token_id in token_ids:
            msg = {
                "type": "subscribe",
                "channel": "book",
                "assets_id": token_id,
            }
            try:
                await self._ws.send(json.dumps(msg))
                logger.debug("Subscribed to book updates for %s", token_id)
            except Exception as e:
                logger.error("Failed to subscribe to %s: %s", token_id, e)

    async def unsubscribe(self, token_ids: list[str]) -> None:
        """Unsubscribe from token updates."""
        for token_id in token_ids:
            self._subscribed_tokens.discard(token_id)
        if self._ws:
            for token_id in token_ids:
                msg = {
                    "type": "unsubscribe",
                    "channel": "book",
                    "assets_id": token_id,
                }
                try:
                    await self._ws.send(json.dumps(msg))
                except Exception:
                    pass

    async def stop(self) -> None:
        """Stop the WebSocket connection."""
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None
        logger.info("WebSocket client stopped")
