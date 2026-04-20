"""CLOB WebSocket subscription with in-memory orderbook cache.

The single biggest latency improvement over REST polling. Polymarket's
market channel streams incremental orderbook updates; we maintain a
local copy keyed by token_id that the bot reads instead of HTTP GETs.

Usage (in an asyncio context):

    cache = OrderbookCache()
    ws = CLOBWebSocket(cache)
    asyncio.create_task(ws.run(asset_ids=["tok1", "tok2"]))
    # elsewhere, sync:
    book = cache.get("tok1")

Not wired into the main bot loop yet — doing so requires making bot.py
async. Kept as an optional module so you can opt in when ready.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


@dataclass
class CachedBook:
    token_id: str
    bids: list[dict[str, Any]] = field(default_factory=list)
    asks: list[dict[str, Any]] = field(default_factory=list)
    updated_at: float = 0.0


class OrderbookCache:
    def __init__(self) -> None:
        self._books: dict[str, CachedBook] = {}
        self._lock = Lock()

    def apply_snapshot(self, token_id: str, msg: dict[str, Any]) -> None:
        with self._lock:
            self._books[token_id] = CachedBook(
                token_id=token_id,
                bids=list(msg.get("bids") or []),
                asks=list(msg.get("asks") or []),
                updated_at=time.time(),
            )

    def apply_delta(self, token_id: str, changes: list[dict[str, Any]]) -> None:
        with self._lock:
            book = self._books.get(token_id)
            if book is None:
                return
            for change in changes:
                side = change.get("side", "").lower()
                price = change.get("price")
                size = change.get("size")
                if side not in ("bid", "ask", "buy", "sell") or price is None:
                    continue
                levels = book.bids if side in ("bid", "buy") else book.asks
                _upsert_level(levels, str(price), str(size or "0"))
            book.updated_at = time.time()

    def get(self, token_id: str) -> dict[str, Any] | None:
        with self._lock:
            book = self._books.get(token_id)
            if book is None:
                return None
            return {
                "asset_id": book.token_id,
                "bids": list(book.bids),
                "asks": list(book.asks),
                "updated_at": book.updated_at,
            }

    def size(self) -> int:
        with self._lock:
            return len(self._books)


def _upsert_level(levels: list[dict[str, Any]], price: str, size: str) -> None:
    if float(size) <= 0:
        levels[:] = [lvl for lvl in levels if str(lvl.get("price")) != price]
        return
    for lvl in levels:
        if str(lvl.get("price")) == price:
            lvl["size"] = size
            return
    levels.append({"price": price, "size": size})


class CLOBWebSocket:
    """Maintains a subscription to market events for a set of asset IDs."""

    def __init__(self, cache: OrderbookCache, url: str = WS_URL):
        self.cache = cache
        self.url = url

    async def run(self, asset_ids: list[str], reconnect_delay: float = 2.0) -> None:
        try:
            import websockets  # type: ignore
        except ImportError as e:
            raise RuntimeError("pip install websockets to use CLOBWebSocket") from e

        while True:
            try:
                async with websockets.connect(self.url, ping_interval=20) as ws:
                    await ws.send(json.dumps({
                        "type": "MARKET",
                        "assets_ids": asset_ids,
                    }))
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        self._handle(msg)
            except Exception as e:
                print(f"[ws] disconnected: {type(e).__name__}: {e}")
                await asyncio.sleep(reconnect_delay)

    def _handle(self, msg: Any) -> None:
        events = msg if isinstance(msg, list) else [msg]
        for ev in events:
            if not isinstance(ev, dict):
                continue
            asset = str(ev.get("asset_id") or ev.get("market") or "")
            event_type = ev.get("event_type") or ev.get("type")
            if not asset:
                continue
            if event_type == "book":
                self.cache.apply_snapshot(asset, ev)
            elif event_type == "price_change":
                self.cache.apply_delta(asset, ev.get("changes") or [])
