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

    @property
    def mid(self) -> tuple[float, ...]:
        return tuple((o.best_bid + o.best_ask) / 2 for o in self.outcomes)


def _outcome_from_row(row: dict[str, Any]) -> MarketOutcome | None:
    token_id = str(row.get("clobTokenIds") or row.get("token_id") or "")
    if not token_id:
        return None
    return MarketOutcome(
        token_id=token_id,
        label=row.get("outcome", ""),
        best_bid=float(row.get("bestBid") or 0.0),
        best_ask=float(row.get("bestAsk") or 0.0),
    )


def fetch_active_markets(tags: Iterable[str], limit: int = 200) -> list[Market]:
    """Pull active markets filtered by tag slugs via the Gamma REST API."""
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
        outcomes = []
        raw_outcomes = row.get("outcomes") or []
        raw_prices = row.get("outcomePrices") or []
        raw_tokens = row.get("clobTokenIds") or []
        for i, label in enumerate(raw_outcomes):
            token_id = raw_tokens[i] if i < len(raw_tokens) else ""
            price = float(raw_prices[i]) if i < len(raw_prices) else 0.0
            if not token_id:
                continue
            outcomes.append(MarketOutcome(
                token_id=str(token_id),
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
