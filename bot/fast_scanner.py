"""5分クリプトマーケット専用スキャナー.

Polymarket の /crypto/5M マーケットは標準の events endpoint に
出てこないので、slug を直接生成して markets endpoint を叩く。

slug pattern: {coin}-updown-5m-{unix_timestamp}
例: btc-updown-5m-1776256200

タイムスタンプは次の5分境界のUnix時間。
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import httpx

from polymarket_arbitrage.config import GAMMA_MARKETS_ENDPOINT
from polymarket_arbitrage.models.market import (
    Event,
    Market,
    MarketStatus,
    Token,
)

logger = logging.getLogger(__name__)

# Coins with 5-min markets on Polymarket
COINS_5MIN = os.environ.get("COINS_5MIN", "btc,eth,sol,xrp,doge,hype,bnb").split(",")


def next_5min_timestamp() -> int:
    """Return the Unix timestamp of the next 5-min boundary."""
    now = int(datetime.now(timezone.utc).timestamp())
    return ((now // 300) + 1) * 300


def current_5min_slug(coin: str) -> str:
    """Build the current 5-min market slug for a coin."""
    ts = next_5min_timestamp()
    return f"{coin.lower()}-updown-5m-{ts}"


def _parse_5min_market(data: dict[str, Any]) -> Optional[Market]:
    """Convert Gamma API market JSON to our Market model."""
    import json as _json

    slug = data.get("slug", "")
    if not slug:
        return None

    # outcomes and prices
    outcomes = data.get("outcomes", [])
    prices = data.get("outcomePrices", [])
    if isinstance(outcomes, str):
        outcomes = _json.loads(outcomes)
    if isinstance(prices, str):
        prices = _json.loads(prices)

    clob_ids = data.get("clobTokenIds", [])
    if isinstance(clob_ids, str):
        clob_ids = _json.loads(clob_ids)

    tokens = []
    for i, outcome in enumerate(outcomes):
        try:
            price = float(prices[i]) if i < len(prices) else 0.0
        except (ValueError, TypeError):
            price = 0.0
        token_id = str(clob_ids[i]) if i < len(clob_ids) else ""
        tokens.append(Token(
            token_id=token_id,
            outcome=outcome,  # "Up" or "Down"
            price=price,
        ))

    # end date
    end_date = None
    end_str = data.get("endDate")
    if end_str:
        try:
            end_date = datetime.fromisoformat(str(end_str).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass

    return Market(
        id=str(data.get("id", slug)),
        question=str(data.get("question", slug)),
        condition_id=str(data.get("conditionId", "")),
        slug=slug,
        tokens=tokens,
        status=MarketStatus.ACTIVE,
        volume=float(data.get("volumeNum", 0) or 0),
        liquidity=float(data.get("liquidityNum", 0) or 0),
        end_date=end_date,
        description=str(data.get("description", "")),
    )


async def fetch_coin_market(
    client: httpx.AsyncClient, coin: str, timestamp: int,
) -> Optional[Market]:
    """Fetch a single coin's current 5-min market."""
    slug = f"{coin.lower()}-updown-5m-{timestamp}"
    try:
        resp = await client.get(
            GAMMA_MARKETS_ENDPOINT,
            params={"slug": slug},
            timeout=5.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data:
            return None
        market_data = data[0] if isinstance(data, list) else data
        return _parse_5min_market(market_data)
    except Exception as e:
        logger.debug("Failed to fetch %s: %s", slug, e)
        return None


async def fetch_all_5min_markets() -> list[Market]:
    """Fetch current 5-min markets for all configured coins (parallel)."""
    timestamp = next_5min_timestamp()
    async with httpx.AsyncClient() as client:
        tasks = [fetch_coin_market(client, coin, timestamp) for coin in COINS_5MIN]
        results = await asyncio.gather(*tasks)
    return [m for m in results if m is not None]


def market_to_event(market: Market) -> Event:
    """Wrap a single 5-min market in an Event (for detector compatibility)."""
    return Event(
        id=f"evt_{market.id}",
        title=market.question,
        slug=market.slug,
        markets=[market],
        neg_risk=False,
    )
