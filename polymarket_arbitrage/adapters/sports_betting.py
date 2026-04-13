"""Sports Betting adapter — cross-bookmaker odds arbitrage.

Core insight (same as the paper):
  For a fair book, the sum of implied probabilities = 1.
  In practice bookmakers add margin ("overround"), so sum > 1.
  But across DIFFERENT bookmakers, you can sometimes assemble a
  set of bets where sum < 1 → guaranteed profit ("sure bet" / "arb").

Mapping to core primitives:
  Instrument = one event at one bookmaker (e.g. "Match winner @ Bet365")
  Outcome    = one selection (Home / Draw / Away) with implied probability
  Constraint = SUM_EQUALS_ONE (across the best odds from any bookmaker)

Two detection modes:
  1. Single-book: overround detection (margin analysis)
  2. Cross-book: combine best odds from different bookmakers → arb
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from polymarket_arbitrage.core.primitives import (
    ConstraintKind,
    Direction,
    Instrument,
    Opportunity,
    Outcome,
    Relationship,
    RelationshipKind,
)
from polymarket_arbitrage.core.detectors import (
    detect_sum_constraint,
    detect_relationship_violation,
    flat_fee,
)

DOMAIN = "sports_betting"
# Typical betting exchange commission
EXCHANGE_FEE = flat_fee(0.05)  # 5% commission on winnings


def implied_probability(decimal_odds: float) -> float:
    """Convert decimal odds to implied probability."""
    return 1.0 / decimal_odds if decimal_odds > 0 else 0.0


def _build_instrument(
    event_name: str,
    bookmaker: str,
    selections: dict[str, float],  # label -> decimal odds
    end_date: datetime | None = None,
) -> Instrument:
    """Build an Instrument from bookmaker odds."""
    outcomes = []
    for label, odds in selections.items():
        outcomes.append(Outcome(
            id=f"{bookmaker}_{label}",
            label=label,
            price=implied_probability(odds),
            venue=bookmaker,
            metadata={"decimal_odds": odds},
        ))
    return Instrument(
        id=f"{event_name}@{bookmaker}",
        name=f"{event_name} @ {bookmaker}",
        outcomes=outcomes,
        constraint=ConstraintKind.SUM_EQUALS_ONE,
        venue=bookmaker,
        category="sports",
        end_date=end_date,
    )


def build_cross_book_instrument(
    event_name: str,
    all_books: list[Instrument],
) -> Instrument:
    """Build a synthetic instrument using the BEST odds across all books.

    For each selection, pick the bookmaker offering the highest odds
    (= lowest implied probability).  If the sum of these best implied
    probabilities < 1, we have an arbitrage.
    """
    # Collect all labels
    labels: set[str] = set()
    for book in all_books:
        for o in book.outcomes:
            labels.add(o.label)

    best_outcomes: list[Outcome] = []
    for label in sorted(labels):
        best_odds = 0.0
        best_venue = ""
        for book in all_books:
            for o in book.outcomes:
                if o.label == label:
                    raw_odds = o.metadata.get("decimal_odds", 0.0)
                    if raw_odds > best_odds:
                        best_odds = raw_odds
                        best_venue = book.venue
        if best_odds > 0:
            best_outcomes.append(Outcome(
                id=f"best_{label}",
                label=f"{label} (best@{best_venue})",
                price=implied_probability(best_odds),
                venue=best_venue,
                metadata={"decimal_odds": best_odds, "source_bookmaker": best_venue},
            ))

    return Instrument(
        id=f"cross_book_{event_name}",
        name=f"{event_name} [Best Across Books]",
        outcomes=best_outcomes,
        constraint=ConstraintKind.SUM_EQUALS_ONE,
        venue="cross-book",
        category="sports",
    )


def generate_demo_data() -> tuple[list[Instrument], list[Instrument]]:
    """Generate demo sports betting data with some arb opportunities.

    Returns (single_book_instruments, cross_book_instruments).
    """
    now = datetime.now(timezone.utc)
    tomorrow = now + timedelta(days=1)

    # === Event 1: Premier League — Liverpool vs Arsenal ===
    # Bookmaker margins: Bet365 has 5% overround, William Hill has 4%
    # But cross-book can create < 100%
    event1_books = [
        _build_instrument("Liverpool vs Arsenal", "Bet365", {
            "Liverpool": 2.10, "Draw": 3.40, "Arsenal": 3.50,
        }, tomorrow),
        _build_instrument("Liverpool vs Arsenal", "WilliamHill", {
            "Liverpool": 2.00, "Draw": 3.60, "Arsenal": 3.80,
        }, tomorrow),
        _build_instrument("Liverpool vs Arsenal", "Betfair", {
            "Liverpool": 2.20, "Draw": 3.30, "Arsenal": 3.40,
        }, tomorrow),
    ]
    # Best odds: Liverpool@Betfair 2.20, Draw@WH 3.60, Arsenal@WH 3.80
    # Implied: 1/2.20 + 1/3.60 + 1/3.80 = 0.4545 + 0.2778 + 0.2632 = 0.9955 < 1 → ARB!

    # === Event 2: Champions League — Real Madrid vs Bayern ===
    event2_books = [
        _build_instrument("Real Madrid vs Bayern", "Bet365", {
            "Real Madrid": 2.50, "Draw": 3.20, "Bayern": 2.90,
        }, tomorrow),
        _build_instrument("Real Madrid vs Bayern", "Pinnacle", {
            "Real Madrid": 2.55, "Draw": 3.30, "Bayern": 2.85,
        }, tomorrow),
        _build_instrument("Real Madrid vs Bayern", "888sport", {
            "Real Madrid": 2.45, "Draw": 3.40, "Bayern": 3.00,
        }, tomorrow),
    ]
    # Best: RM@Pinnacle 2.55, Draw@888 3.40, Bayern@888 3.00
    # Implied: 0.3922 + 0.2941 + 0.3333 = 1.0196 > 1 → no arb

    # === Event 3: NBA — Lakers vs Celtics (2-way, no draw) ===
    event3_books = [
        _build_instrument("Lakers vs Celtics", "DraftKings", {
            "Lakers": 2.30, "Celtics": 1.65,
        }, tomorrow),
        _build_instrument("Lakers vs Celtics", "FanDuel", {
            "Lakers": 2.40, "Celtics": 1.60,
        }, tomorrow),
    ]
    # Best: Lakers@FanDuel 2.40, Celtics@DraftKings 1.65
    # Implied: 0.4167 + 0.6061 = 1.0228 → no arb
    # But Lakers@FanDuel 2.40, Celtics@FanDuel 1.60 → 0.4167 + 0.625 = 1.0417

    # === Event 4: Tennis — Djokovic vs Sinner (sharp arb) ===
    event4_books = [
        _build_instrument("Djokovic vs Sinner", "Betway", {
            "Djokovic": 1.80, "Sinner": 2.10,
        }, tomorrow),
        _build_instrument("Djokovic vs Sinner", "Unibet", {
            "Djokovic": 1.95, "Sinner": 1.90,
        }, tomorrow),
    ]
    # Best: Djokovic@Unibet 1.95, Sinner@Betway 2.10
    # Implied: 0.5128 + 0.4762 = 0.9890 < 1 → ARB!

    all_single = event1_books + event2_books + event3_books + event4_books

    # Build cross-book synthetics
    events = {
        "Liverpool vs Arsenal": event1_books,
        "Real Madrid vs Bayern": event2_books,
        "Lakers vs Celtics": event3_books,
        "Djokovic vs Sinner": event4_books,
    }
    cross_books = [
        build_cross_book_instrument(name, books)
        for name, books in events.items()
    ]

    return all_single, cross_books


def detect(
    single_books: list[Instrument],
    cross_books: list[Instrument],
) -> list[Opportunity]:
    """Run sports betting arbitrage detection."""
    opps: list[Opportunity] = []

    # 1. Single-book overround analysis
    opps.extend(detect_sum_constraint(
        single_books, target=1.0, threshold=0.001,
        fee_func=EXCHANGE_FEE, domain=DOMAIN,
    ))

    # 2. Cross-book arb (the main event)
    opps.extend(detect_sum_constraint(
        cross_books, target=1.0, threshold=0.001,
        fee_func=EXCHANGE_FEE, domain=DOMAIN,
    ))

    return opps
