"""Discover and normalise Polymarket BTC Up/Down markets.

Polymarket runs frequent short-horizon "Bitcoin Up or Down - <date>,
<time> ET" markets. Each market typically has two outcomes (``Up`` and
``Down``), a start and a close time, and a reference price embedded in
the slug or question text.

This module parses that metadata into a single, pricing-friendly schema::

    UpDownMarket(
        condition_id, slug, question,
        up_token_id, down_token_id,
        open_ts, close_ts,
        reference_price,   # strike (K)
        start_spot,        # S_0 at market start, optional
    )

The parser is defensive: Polymarket has changed question wording several
times. We log and skip markets we cannot parse rather than raising.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Iterable

from .polymarket_client import PolymarketClient

logger = logging.getLogger(__name__)


# Example questions we must handle:
#   "Bitcoin Up or Down - March 29, 1AM ET"
#   "Will Bitcoin be up or down at 4:05AM ET on April 7?"
# Reference price / strike sometimes appears in market.description as
# "Up at $68,712.80" or embedded in the subtitle. We therefore search
# across several fields.
_PRICE_RE = re.compile(r"\$?\s*([0-9]{4,6}(?:[.,][0-9]+)?)")
_TIME_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(AM|PM)\s*ET", re.IGNORECASE)


@dataclass(frozen=True)
class UpDownMarket:
    condition_id: str
    slug: str
    question: str
    up_token_id: str | None
    down_token_id: str | None
    open_ts: int  # unix seconds UTC
    close_ts: int
    reference_price: float | None
    start_spot: float | None = None

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
    """Return parsed Up/Down markets in ``[since_ts, until_ts]``."""
    events = client.search_events("bitcoin up or down", limit=limit)
    out: list[UpDownMarket] = []
    for ev in events:
        for m in ev.get("markets", []) or []:
            parsed = _parse_market(m)
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
# Parsing helpers. Kept pure for easy unit testing with fixture JSON.
# ---------------------------------------------------------------------------


def _parse_market(raw: dict[str, Any]) -> UpDownMarket | None:
    question = raw.get("question") or raw.get("title") or ""
    slug = raw.get("slug") or ""
    cid = raw.get("conditionId") or raw.get("condition_id") or raw.get("id")
    if not cid:
        return None
    if "bitcoin" not in question.lower() and "btc" not in slug.lower():
        return None
    if not any(k in question.lower() for k in ("up or down", "up/down", "higher or lower")):
        return None

    up_tok, down_tok = _extract_token_ids(raw)
    open_ts = _parse_ts(
        raw.get("startDate") or raw.get("startTime") or raw.get("start_time")
    )
    close_ts = _parse_ts(
        raw.get("endDate") or raw.get("endTime") or raw.get("end_time")
    )
    if open_ts is None or close_ts is None:
        logger.debug("missing timestamps for %s; skipping", slug)
        return None

    reference = _extract_reference_price(raw)
    return UpDownMarket(
        condition_id=str(cid),
        slug=str(slug),
        question=str(question),
        up_token_id=up_tok,
        down_token_id=down_tok,
        open_ts=open_ts,
        close_ts=close_ts,
        reference_price=reference,
    )


def _extract_token_ids(raw: dict[str, Any]) -> tuple[str | None, str | None]:
    """Find the Up and Down CLOB token IDs from a Gamma market payload."""
    outcomes = raw.get("outcomes") or []
    tokens = raw.get("clobTokenIds") or raw.get("tokens") or []
    # outcomes and tokens are parallel arrays in the current Gamma schema.
    if isinstance(tokens, str):
        # Gamma sometimes returns a JSON-encoded list inside a string.
        import json

        try:
            tokens = json.loads(tokens)
        except Exception:
            tokens = []
    if isinstance(outcomes, str):
        import json

        try:
            outcomes = json.loads(outcomes)
        except Exception:
            outcomes = []
    up_tok = down_tok = None
    for label, tok in zip(outcomes, tokens):
        name = str(label).lower()
        if name in {"up", "yes", "higher"}:
            up_tok = str(tok)
        elif name in {"down", "no", "lower"}:
            down_tok = str(tok)
    return up_tok, down_tok


def _parse_ts(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value) if value > 1e10 else int(value)  # already ms or s
    try:
        # Gamma returns ISO-8601 strings in UTC.
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except ValueError:
        return None


def _extract_reference_price(raw: dict[str, Any]) -> float | None:
    for field_name in ("description", "question", "subtitle", "slug"):
        text = raw.get(field_name) or ""
        m = _PRICE_RE.search(str(text))
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                continue
    return None
