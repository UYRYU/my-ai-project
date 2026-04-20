"""Canned market data for offline dry-run demos.

Includes:
- A clear single-market arb (sum of asks < 1.0)
- A no-arb market (sum > 1.0, the normal case)
- Two markets for the same event (so event_grouper has something to group)
"""

from .polymarket import Market, MarketOutcome


def markets() -> list[Market]:
    return [
        # Real arb: 0.45 + 0.50 = 0.95 → 5 cents of free edge per dollar
        Market(
            condition_id="0xMOCK_ARB",
            question="Will the Lakers beat the Celtics tonight?",
            slug="nba-lakers-vs-celtics-2026-04-19-moneyline",
            end_date="2026-04-20T03:00:00Z",
            category="sports",
            outcomes=(
                MarketOutcome(token_id="tok_lakers_ml", label="Lakers", best_bid=0.44, best_ask=0.45),
                MarketOutcome(token_id="tok_celtics_ml", label="Celtics", best_bid=0.49, best_ask=0.50),
            ),
        ),
        # Same event, different market — for event_grouper to bind
        Market(
            condition_id="0xMOCK_SPREAD",
            question="Will the Lakers cover -3.5?",
            slug="nba-lakers-vs-celtics-2026-04-19-spread-lakers-3p5",
            end_date="2026-04-20T03:00:00Z",
            category="sports",
            outcomes=(
                MarketOutcome(token_id="tok_lakers_cover", label="Yes", best_bid=0.39, best_ask=0.41),
                MarketOutcome(token_id="tok_lakers_nocover", label="No", best_bid=0.59, best_ask=0.61),
            ),
        ),
        # Healthy market: asks sum to 1.02 — no arb, normal venue rake
        Market(
            condition_id="0xMOCK_NORMAL",
            question="Will the Warriors beat the Suns?",
            slug="nba-warriors-vs-suns-2026-04-19-moneyline",
            end_date="2026-04-20T03:00:00Z",
            category="sports",
            outcomes=(
                MarketOutcome(token_id="tok_warriors_ml", label="Warriors", best_bid=0.50, best_ask=0.51),
                MarketOutcome(token_id="tok_suns_ml", label="Suns", best_bid=0.50, best_ask=0.51),
            ),
        ),
    ]


def orderbook(token_id: str) -> dict:
    """Mock CLOB book — enough depth on every leg for the test arb basket."""
    base_ask = {
        "tok_lakers_ml": 0.45,
        "tok_celtics_ml": 0.50,
        "tok_lakers_cover": 0.41,
        "tok_lakers_nocover": 0.61,
        "tok_warriors_ml": 0.51,
        "tok_suns_ml": 0.51,
    }.get(token_id, 0.50)
    return {
        "asset_id": token_id,
        "bids": [{"price": str(base_ask - 0.01), "size": "500"}],
        "asks": [
            {"price": str(base_ask), "size": "200"},
            {"price": str(base_ask + 0.01), "size": "500"},
        ],
    }
