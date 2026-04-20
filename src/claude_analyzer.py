"""Claude-powered analyzer for cross-market correlations.

The arithmetic arb in `arbitrage.py` only catches single-market mispricings.
Real sovereign2013-style edges come from *correlated* markets: e.g. a
moneyline market on Game X and a separate "Team A wins by 5+" market.
We ask Claude to group correlated markets and propose basket trades whose
implied probabilities don't sum coherently.

The market list is large and repeats across ticks, so we put it behind a
cache breakpoint. Only the question ("find new correlations since tick N")
changes per request.
"""

import json
from dataclasses import dataclass
from anthropic import Anthropic
from .polymarket import Market

MODEL = "claude-opus-4-7"


@dataclass(frozen=True)
class CorrelatedBasket:
    rationale: str
    legs: tuple[tuple[str, str, float], ...]
    implied_sum: float
    suggested_action: str


def _serialize(markets: list[Market]) -> str:
    rows = [
        {
            "condition_id": m.condition_id,
            "question": m.question,
            "end_date": m.end_date,
            "outcomes": [
                {"token_id": o.token_id, "label": o.label, "bid": o.best_bid, "ask": o.best_ask}
                for o in m.outcomes
            ],
        }
        for m in markets
    ]
    return json.dumps(rows, sort_keys=True, separators=(",", ":"))


SYSTEM_PROMPT = (
    "You are an arbitrage scout for Polymarket sports markets. "
    "You are given a deterministic JSON list of active markets. Identify "
    "baskets of outcomes across DIFFERENT markets whose implied probabilities "
    "must sum to a known constant (typically 1.0) by construction — e.g. "
    "complementary moneylines across two listings of the same game, mutually "
    "exclusive spread buckets that partition the outcome space, or "
    "over/under pairs on the same line. "
    "Return STRICT JSON: a list of baskets. Each basket has "
    '{"rationale": str, "expected_sum": float, "legs": [{"condition_id": str, '
    '"token_id": str, "label": str, "side": "BUY"|"SELL", "price": float}]}. '
    "Only return baskets where |actual_sum - expected_sum| >= 0.01. "
    "If nothing qualifies, return []."
)


def find_correlated_baskets(client: Anthropic, markets: list[Market]) -> list[CorrelatedBasket]:
    if not markets:
        return []
    payload = _serialize(markets)
    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            },
            {
                "type": "text",
                "text": f"MARKET_SNAPSHOT_JSON:\n{payload}",
                "cache_control": {"type": "ephemeral"},
            },
        ],
        messages=[
            {"role": "user", "content": "Scan the snapshot and return qualifying baskets as JSON."}
        ],
    )
    text = next((b.text for b in response.content if b.type == "text"), "[]")
    try:
        raw = json.loads(_extract_json(text))
    except json.JSONDecodeError:
        return []

    baskets: list[CorrelatedBasket] = []
    for b in raw:
        legs = tuple(
            (leg["token_id"], leg.get("side", "BUY"), float(leg["price"]))
            for leg in b.get("legs", [])
        )
        if not legs:
            continue
        implied = sum(p for _, side, p in legs if side == "BUY") - sum(
            p for _, side, p in legs if side == "SELL"
        )
        baskets.append(CorrelatedBasket(
            rationale=b.get("rationale", ""),
            legs=legs,
            implied_sum=implied,
            suggested_action=b.get("rationale", ""),
        ))
    return baskets


def _extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0]
    return text.strip()
