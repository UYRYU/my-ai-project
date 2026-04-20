"""Discover and normalise Polymarket BTC Up/Down markets.

Schema notes (verified against the public Polymarket Gamma schema as of
2026-04; see polymarket-kit `MarketSchema` / `EventSchema`):

* ``outcomes``, ``outcomePrices``, ``clobTokenIds`` are returned as JSON
  strings -- e.g. ``'["Up","Down"]'`` -- not native arrays. We always
  parse them defensively.
* Events carry ``markets[]`` nested under them. Each market has its own
  ``conditionId``, ``slug``, ``question``, and ``groupItemTitle`` which
  for Up/Down binaries typically encodes the strike (e.g. "Up at
  $68,712.80" or "68,712.80").
* ISO timestamps live in ``startDate`` / ``endDate`` (fallback keys
  ``startDateIso`` / ``endDateIso``).
* Settlement metadata: ``umaResolutionStatus``, ``automaticallyResolved``,
  ``resolvedBy`` at the market level; ``resolutionSource`` at the event
  level.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Iterable

from .polymarket_client import PolymarketClient

logger = logging.getLogger(__name__)


# Up/Down markets embed the strike in various places. We search a ranked
# list of fields for a plausible $-qualified price. The regex requires a
# comma or decimal to avoid matching volume counts like "7712".
_PRICE_RE = re.compile(r"\$\s*([0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?|[0-9]+\.[0-9]+)")
_STRIKE_FIELDS = ("groupItemTitle", "question", "description", "slug")


@dataclass(frozen=True)
class UpDownMarket:
    condition_id: str
    market_id: str
    event_id: str | None
    slug: str
    question: str
    up_token_id: str | None
    down_token_id: str | None
    open_ts: int
    close_ts: int
    reference_price: float | None
    resolution_source: str | None = None
    resolved: bool = False
    resolved_outcome: str | None = None  # "UP" or "DOWN" when known
    last_trade_price: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_up_down_markets(
    client: PolymarketClient,
    *,
    since_ts: int | None = None,
    until_ts: int | None = None,
    limit: int = 500,
    include_closed: bool = True,
) -> list[UpDownMarket]:
    events = client.search_events("bitcoin up or down", limit=limit)
    out: list[UpDownMarket] = []
    for ev in events:
        res_source = ev.get("resolutionSource")
        ev_id = str(ev.get("id")) if ev.get("id") is not None else None
        for m in ev.get("markets") or []:
            parsed = _parse_market(m, event_id=ev_id, resolution_source=res_source)
            if parsed is None:
                continue
            if since_ts is not None and parsed.close_ts < since_ts:
                continue
            if until_ts is not None and parsed.open_ts > until_ts:
                continue
            if not include_closed and parsed.close_ts < int(datetime.now(timezone.utc).timestamp()):
                continue
            out.append(parsed)
    logger.info("loaded %d Up/Down markets", len(out))
    return out


def filter_active(markets: Iterable[UpDownMarket], now_ts: int) -> list[UpDownMarket]:
    return [m for m in markets if m.open_ts <= now_ts <= m.close_ts]


# ---------------------------------------------------------------------------
# Parsing (pure; unit-testable with fixture JSON)
# ---------------------------------------------------------------------------


def _parse_market(
    raw: dict[str, Any],
    *,
    event_id: str | None = None,
    resolution_source: str | None = None,
) -> UpDownMarket | None:
    cid = raw.get("conditionId") or raw.get("condition_id")
    mid = raw.get("id")
    if not cid or not mid:
        return None

    question = str(raw.get("question") or "")
    slug = str(raw.get("slug") or "")
    lower_q = question.lower()
    lower_s = slug.lower()
    if "bitcoin" not in lower_q and "btc" not in lower_q and "bitcoin" not in lower_s:
        return None
    if not any(k in lower_q for k in ("up or down", "up/down", "higher or lower")):
        # Permit slug-only matches for the "btc-up-or-down-..." pattern.
        if "up-or-down" not in lower_s:
            return None

    outcomes = _parse_string_array(raw.get("outcomes"))
    tokens = _parse_string_array(raw.get("clobTokenIds"))
    outcome_prices = _parse_string_array(raw.get("outcomePrices"))
    up_tok, down_tok = _match_tokens(outcomes, tokens)

    open_ts = _parse_ts(raw.get("startDate") or raw.get("startDateIso") or raw.get("startTime"))
    close_ts = _parse_ts(raw.get("endDate") or raw.get("endDateIso") or raw.get("endTime"))
    if open_ts is None or close_ts is None:
        logger.debug("missing timestamps for %s; skipping", slug)
        return None

    reference = _extract_reference_price(raw)

    closed = bool(raw.get("closed"))
    uma_status = (raw.get("umaResolutionStatus") or "").lower()
    auto_resolved = bool(raw.get("automaticallyResolved"))
    resolved = closed and (uma_status in {"resolved", "done"} or auto_resolved)

    resolved_outcome = _extract_resolved_outcome(outcomes, outcome_prices) if resolved else None
    last_price = _safe_float(raw.get("lastTradePrice"))

    return UpDownMarket(
        condition_id=str(cid),
        market_id=str(mid),
        event_id=event_id,
        slug=slug,
        question=question,
        up_token_id=up_tok,
        down_token_id=down_tok,
        open_ts=open_ts,
        close_ts=close_ts,
        reference_price=reference,
        resolution_source=resolution_source,
        resolved=resolved,
        resolved_outcome=resolved_outcome,
        last_trade_price=last_price,
    )


def _parse_string_array(value: Any) -> list[str]:
    """Parse Gamma's stringified-array fields into native lists."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x) for x in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return [str(x) for x in parsed]
    return []


def _match_tokens(outcomes: list[str], tokens: list[str]) -> tuple[str | None, str | None]:
    if not outcomes or not tokens:
        return None, None
    up_tok = down_tok = None
    for label, tok in zip(outcomes, tokens):
        name = label.strip().lower()
        if name in {"up", "yes", "higher"}:
            up_tok = tok
        elif name in {"down", "no", "lower"}:
            down_tok = tok
    # Fallback: assume positional [Up, Down] when labels don't match.
    if up_tok is None and down_tok is None and len(tokens) >= 2:
        up_tok, down_tok = tokens[0], tokens[1]
    return up_tok, down_tok


def _extract_resolved_outcome(outcomes: list[str], prices: list[str]) -> str | None:
    """After resolution, Gamma sets outcomePrices to [1, 0] or [0, 1]."""
    if len(outcomes) != len(prices) or not outcomes:
        return None
    nums: list[float] = []
    for p in prices:
        try:
            nums.append(float(p))
        except ValueError:
            return None
    winner_idx = max(range(len(nums)), key=lambda i: nums[i])
    # Treat only near-degenerate distributions as "settled" (typical
    # post-resolution values are exactly 1 and 0).
    if nums[winner_idx] < 0.99:
        return None
    label = outcomes[winner_idx].strip().lower()
    if label in {"up", "yes", "higher"}:
        return "UP"
    if label in {"down", "no", "lower"}:
        return "DOWN"
    return None


def _parse_ts(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        # Gamma has been seen to return milliseconds; detect and normalise.
        return int(v / 1000.0) if v > 1e11 else int(v)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except ValueError:
        return None


def _safe_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _extract_reference_price(raw: dict[str, Any]) -> float | None:
    for field_name in _STRIKE_FIELDS:
        text = raw.get(field_name) or ""
        m = _PRICE_RE.search(str(text))
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                continue
    # Last resort: a raw groupItemThreshold if numeric.
    thr = _safe_float(raw.get("groupItemThreshold"))
    return thr
