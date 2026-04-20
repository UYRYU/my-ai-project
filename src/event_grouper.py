"""Group markets that refer to the same underlying event.

Sovereign2013-style cross-market arb requires knowing which markets are
talking about the same game. Polymarket often lists:
  - moneyline ("Will Lakers beat Celtics?")
  - spread buckets ("Lakers by 5+", "Lakers by 1-4", "Celtics by 1-4", ...)
  - totals ("Over 220.5", "Under 220.5")
all for one game. The slug usually shares a prefix like
`nba-lakers-vs-celtics-2026-04-19`.

This is a cheap heuristic that runs every tick, before we spend tokens
on the Claude scout. Claude only sees groups that are too ambiguous to
pair locally.
"""

import re
from collections import defaultdict
from .polymarket import Market

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}$")
_TEAM_PAIR_RE = re.compile(r"([a-z0-9]+)-vs-([a-z0-9]+)")


def event_key(market: Market) -> str | None:
    """Derive a stable key for the underlying event from the market slug.

    Returns None if the slug doesn't look like a sports game.
    """
    slug = (market.slug or "").lower()
    if not slug:
        return None
    pair = _TEAM_PAIR_RE.search(slug)
    if not pair:
        return None
    teams = sorted([pair.group(1), pair.group(2)])
    date_match = _DATE_RE.search(slug)
    date = date_match.group(0) if date_match else (market.end_date or "")[:10]
    return f"{teams[0]}-vs-{teams[1]}@{date}"


def group_by_event(markets: list[Market]) -> dict[str, list[Market]]:
    groups: dict[str, list[Market]] = defaultdict(list)
    for m in markets:
        key = event_key(m)
        if key is None:
            continue
        groups[key].append(m)
    # only keep events with >1 market — single-market events have no
    # cross-market arb to find here.
    return {k: v for k, v in groups.items() if len(v) > 1}
