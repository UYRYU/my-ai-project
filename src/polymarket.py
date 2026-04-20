import json
from dataclasses import dataclass
from typing import Any, Iterable
import httpx

GAMMA_API = "https://gamma-api.polymarket.com"


@dataclass(frozen=True)
class MarketOutcome:
    token_id: str
    label: str
    best_bid: float
    best_ask: float


@dataclass(frozen=True)
class Market:
    condition_id: str
    question: str
    slug: str
    end_date: str | None
    category: str | None
    outcomes: tuple[MarketOutcome, ...]
    volume_24h: float = 0.0
    liquidity: float = 0.0

    @property
    def mid(self) -> tuple[float, ...]:
        return tuple((o.best_bid + o.best_ask) / 2 for o in self.outcomes)


def _parse_maybe_json_list(value: Any) -> list[Any]:
    """Gamma returns `outcomes`, `outcomePrices`, `clobTokenIds` as JSON strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return []
        try:
            parsed = json.loads(s)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def fetch_active_markets(tags: Iterable[str], limit: int = 200) -> list[Market]:
    """Pull active markets filtered by tag slugs via the Gamma REST API.

    Gamma prices are a 1-tick snapshot — fine for discovery, NOT for
    execution. Use `fetch_orderbook` to get real depth before placing.
    """
    params = {
        "active": "true",
        "closed": "false",
        "archived": "false",
        "limit": str(limit),
        "tag_slug": ",".join(tags),
    }
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(f"{GAMMA_API}/markets", params=params)
        resp.raise_for_status()
        rows = resp.json()

    markets: list[Market] = []
    for row in rows:
        labels = _parse_maybe_json_list(row.get("outcomes"))
        prices = _parse_maybe_json_list(row.get("outcomePrices"))
        tokens = _parse_maybe_json_list(row.get("clobTokenIds"))
        outcomes: list[MarketOutcome] = []
        for i, label in enumerate(labels):
            token_id = str(tokens[i]) if i < len(tokens) else ""
            try:
                price = float(prices[i]) if i < len(prices) else 0.0
            except (TypeError, ValueError):
                price = 0.0
            if not token_id:
                continue
            outcomes.append(MarketOutcome(
                token_id=token_id,
                label=str(label),
                best_bid=price,
                best_ask=price,
            ))
        if len(outcomes) < 2:
            continue
        markets.append(Market(
            condition_id=row.get("conditionId", ""),
            question=row.get("question", ""),
            slug=row.get("slug", ""),
            end_date=row.get("endDate"),
            category=row.get("category"),
            outcomes=tuple(outcomes),
            volume_24h=float(row.get("volume24hr") or 0.0),
            liquidity=float(row.get("liquidity") or 0.0),
        ))
    return markets


def fetch_orderbook(clob_host: str, token_id: str) -> dict[str, Any]:
    """Fetch live bid/ask depth for one outcome token from the CLOB."""
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(f"{clob_host}/book", params={"token_id": token_id})
        resp.raise_for_status()
        return resp.json()


def top_of_book(book: dict[str, Any]) -> tuple[float, float]:
    bids = book.get("bids") or []
    asks = book.get("asks") or []
    best_bid = float(bids[0]["price"]) if bids else 0.0
    best_ask = float(asks[0]["price"]) if asks else 1.0
    return best_bid, best_ask
