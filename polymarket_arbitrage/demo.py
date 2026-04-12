"""Demo data for testing the pipeline without API access.

Generates synthetic events and markets that simulate realistic
Polymarket data, including some with built-in arbitrage opportunities.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from polymarket_arbitrage.models.market import Event, Market, MarketStatus, Token


def _make_market(
    id: str,
    question: str,
    yes_price: float,
    no_price: float,
    *,
    end_date: datetime | None = None,
    description: str = "",
) -> Market:
    return Market(
        id=id,
        question=question,
        condition_id=f"cond_{id}",
        slug=question.lower().replace(" ", "-")[:40],
        tokens=[
            Token(token_id=f"tok_{id}_yes", outcome="Yes", price=yes_price),
            Token(token_id=f"tok_{id}_no", outcome="No", price=no_price),
        ],
        status=MarketStatus.ACTIVE,
        volume=100_000,
        liquidity=50_000,
        end_date=end_date,
        description=description,
    )


def generate_demo_events() -> list[Event]:
    """Generate demo events with some arbitrage opportunities baked in."""
    now = datetime.now(timezone.utc)
    end_soon = now + timedelta(days=7)
    end_later = now + timedelta(days=30)

    events = []

    # ------------------------------------------------------------------
    # 1. Normal binary market (no arbitrage) - prices sum to 1.0
    # ------------------------------------------------------------------
    events.append(Event(
        id="evt_1",
        title="Will BTC reach $100k by end of year?",
        slug="btc-100k",
        markets=[_make_market(
            "m1", "Will Bitcoin reach $100,000 by Dec 31?",
            yes_price=0.45, no_price=0.55,
            end_date=end_later,
            description="Resolves YES if Bitcoin price >= $100,000 on any exchange before Dec 31.",
        )],
    ))

    # ------------------------------------------------------------------
    # 2. Single-condition arbitrage (YES + NO < 1 → LONG)
    # ------------------------------------------------------------------
    events.append(Event(
        id="evt_2",
        title="Will ETH flip BTC market cap?",
        slug="eth-flip-btc",
        markets=[_make_market(
            "m2", "Will Ethereum's market cap exceed Bitcoin's in 2026?",
            yes_price=0.08, no_price=0.85,  # sum = 0.93, gap = 0.07
            end_date=end_later,
            description="Resolves YES if ETH market cap > BTC market cap at any point in 2026.",
        )],
    ))

    # ------------------------------------------------------------------
    # 3. Single-condition arbitrage (YES + NO > 1 → SHORT)
    # ------------------------------------------------------------------
    events.append(Event(
        id="evt_3",
        title="Fed rate decision June 2026",
        slug="fed-rate-june",
        markets=[_make_market(
            "m3", "Will the Fed cut rates in June 2026?",
            yes_price=0.62, no_price=0.45,  # sum = 1.07, excess = 0.07
            end_date=end_soon,
            description="Resolves YES if the Federal Reserve lowers the federal funds rate at the June FOMC meeting.",
        )],
    ))

    # ------------------------------------------------------------------
    # 4. NegRisk event with arbitrage (sum of YES < 1 → LONG)
    # ------------------------------------------------------------------
    events.append(Event(
        id="evt_4",
        title="2026 FIFA World Cup Winner",
        slug="world-cup-2026-winner",
        neg_risk=True,
        markets=[
            _make_market("m4a", "Will Brazil win the 2026 World Cup?",
                         yes_price=0.18, no_price=0.82, end_date=end_later),
            _make_market("m4b", "Will France win the 2026 World Cup?",
                         yes_price=0.15, no_price=0.85, end_date=end_later),
            _make_market("m4c", "Will Argentina win the 2026 World Cup?",
                         yes_price=0.20, no_price=0.80, end_date=end_later),
            _make_market("m4d", "Will England win the 2026 World Cup?",
                         yes_price=0.10, no_price=0.90, end_date=end_later),
            _make_market("m4e", "Will Germany win the 2026 World Cup?",
                         yes_price=0.08, no_price=0.92, end_date=end_later),
            _make_market("m4f", "Will another team win the 2026 World Cup?",
                         yes_price=0.20, no_price=0.80, end_date=end_later),
        ],
        # sum(YES) = 0.18+0.15+0.20+0.10+0.08+0.20 = 0.91 → 0.09 gap
    ))

    # ------------------------------------------------------------------
    # 5. NegRisk event with arbitrage (sum of YES > 1 → SHORT)
    # ------------------------------------------------------------------
    events.append(Event(
        id="evt_5",
        title="Next US President Party",
        slug="next-president-party",
        neg_risk=True,
        markets=[
            _make_market("m5a", "Will a Democrat win the 2028 Presidential Election?",
                         yes_price=0.52, no_price=0.48, end_date=end_later),
            _make_market("m5b", "Will a Republican win the 2028 Presidential Election?",
                         yes_price=0.48, no_price=0.52, end_date=end_later),
            _make_market("m5c", "Will a Third Party win the 2028 Presidential Election?",
                         yes_price=0.05, no_price=0.95, end_date=end_later),
        ],
        # sum(YES) = 0.52+0.48+0.05 = 1.05 → 0.05 excess
    ))

    # ------------------------------------------------------------------
    # 6 & 7. Cross-market pair for combinatorial arbitrage
    # Subset relationship: "Trump wins popular vote" ⊂ "Trump wins presidency"
    # but prices are inverted (sub > sup) → arbitrage
    # ------------------------------------------------------------------
    events.append(Event(
        id="evt_6",
        title="2028 Election - Popular Vote",
        slug="2028-popular-vote",
        markets=[_make_market(
            "m6", "Will the Republican candidate win the popular vote in 2028?",
            yes_price=0.42, no_price=0.58,
            end_date=end_later,
            description="Resolves YES if the Republican presidential candidate wins the popular vote.",
        )],
    ))

    events.append(Event(
        id="evt_7",
        title="2028 Election - Presidency",
        slug="2028-presidency",
        markets=[_make_market(
            "m7", "Will the Republican candidate win the 2028 Presidential Election?",
            yes_price=0.38, no_price=0.62,
            end_date=end_later,
            description="Resolves YES if the Republican candidate wins the Electoral College.",
        )],
    ))

    # ------------------------------------------------------------------
    # 8 & 9. Complement pair: two markets that should sum to 1
    # "Will inflation be above 3%?" vs "Will inflation be 3% or below?"
    # ------------------------------------------------------------------
    events.append(Event(
        id="evt_8",
        title="US Inflation Above 3%",
        slug="inflation-above-3",
        markets=[_make_market(
            "m8", "Will US CPI inflation be above 3% in December 2026?",
            yes_price=0.35, no_price=0.65,
            end_date=end_later,
            description="Resolves YES if December 2026 CPI YoY > 3%.",
        )],
    ))

    events.append(Event(
        id="evt_9",
        title="US Inflation 3% or Below",
        slug="inflation-at-or-below-3",
        markets=[_make_market(
            "m9", "Will US CPI inflation be 3% or below in December 2026?",
            yes_price=0.58, no_price=0.42,
            end_date=end_later,
            description="Resolves YES if December 2026 CPI YoY <= 3%.",
        )],
        # m8.YES + m9.YES = 0.35 + 0.58 = 0.93 (should be 1.0 → gap = 0.07)
    ))

    return events
