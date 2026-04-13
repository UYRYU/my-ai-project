#!/usr/bin/env python3
"""Multi-domain arbitrage demo.

Demonstrates how the core logic from arXiv:2508.03474 generalises
across four different financial domains:

  1. Prediction Markets (Polymarket) — the paper's original domain
  2. Sports Betting — cross-bookmaker odds arbitrage
  3. DeFi — cross-DEX and triangular token arbitrage
  4. Options — Put-Call Parity, cross-exchange, box spread

All four share the same mathematical foundation:
  "A set of related prices should satisfy a constraint.
   When the constraint is violated, profit is guaranteed."
"""

from __future__ import annotations

import sys
import time


def header(title: str) -> None:
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def section(title: str) -> None:
    print(f"\n  --- {title} ---")


def run_prediction_markets() -> int:
    """Domain 1: Polymarket (paper's original)."""
    header("DOMAIN 1: PREDICTION MARKETS (Polymarket)")
    print("  Core constraint: sum(outcome_prices) = $1.00")
    print("  Paper: Saguillo et al., 'Unravelling the Probabilistic Forest'")

    from polymarket_arbitrage.demo import generate_demo_events
    from polymarket_arbitrage.arbitrage.intra_market import detect_all_intra_market

    events = generate_demo_events()
    opps = detect_all_intra_market(events)

    section(f"Results: {len(opps)} opportunities from {len(events)} events")
    for o in sorted(opps, key=lambda x: -x.net_profit_per_dollar)[:5]:
        print(f"    [{o.direction.value.upper():5s}] {o.description[:70]}")
        print(f"           net profit: ${o.net_profit_per_dollar:.4f}/dollar")

    return len(opps)


def run_sports_betting() -> int:
    """Domain 2: Sports betting cross-bookmaker arbitrage."""
    header("DOMAIN 2: SPORTS BETTING (Cross-Bookmaker)")
    print("  Core constraint: sum(1/odds_i) = 1.00 for fair book")
    print("  Cross-book: combine best odds from different bookmakers")

    from polymarket_arbitrage.adapters.sports_betting import generate_demo_data, detect

    single_books, cross_books = generate_demo_data()
    opps = detect(single_books, cross_books)

    # Separate single-book overround from cross-book arbs
    single_book_opps = [o for o in opps if "Best Across" not in o.instruments[0].name]
    cross_book_opps = [o for o in opps if "Best Across" in o.instruments[0].name]

    section(f"Single-bookmaker overround: {len(single_book_opps)} books with margin > 0")
    for o in single_book_opps[:4]:
        margin = o.price_sum - 1.0
        dir_label = "overround" if o.direction.value == "short" else "underround"
        print(f"    [{dir_label:10s}] {o.instruments[0].name}: "
              f"sum={o.price_sum:.4f} (margin={margin:+.4f})")

    section(f"Cross-bookmaker arbs: {len(cross_book_opps)} opportunities")
    for o in cross_book_opps:
        details = o.instruments[0].outcomes
        print(f"    [{o.direction.value.upper():5s}] {o.instruments[0].name}")
        for out in details:
            odds = out.metadata.get("decimal_odds", 0)
            print(f"           {out.label}: odds={odds:.2f} "
                  f"(implied={out.price:.4f}) via {out.metadata.get('source_bookmaker', out.venue)}")
        print(f"           sum(implied)={o.price_sum:.4f}, "
              f"net profit: ${o.net_profit:.4f}/dollar")

    return len(opps)


def run_defi() -> int:
    """Domain 3: DeFi cross-DEX and triangular arbitrage."""
    header("DOMAIN 3: DeFi (Cross-DEX & Triangular)")
    print("  Core constraint: same asset, same price everywhere")
    print("  Triangle: A/B × B/C × C/A = 1.00")

    from polymarket_arbitrage.adapters.defi import generate_demo_data, detect

    instruments = generate_demo_data()
    opps = detect(instruments)

    cross_dex = [o for o in opps if "Cross-DEX" in o.description]
    triangles = [o for o in opps if "Triangle" in o.description]

    section(f"Cross-DEX arbs: {len(cross_dex)} opportunities")
    for o in cross_dex:
        print(f"    {o.description}")
        print(f"           net profit: ${o.net_profit:.4f}")

    section(f"Triangular arbs: {len(triangles)} opportunities")
    for o in triangles:
        print(f"    {o.description}")
        print(f"           net profit: ${o.net_profit:.6f}")

    return len(opps)


def run_options() -> int:
    """Domain 4: Options arbitrage."""
    header("DOMAIN 4: OPTIONS (Parity / Cross-Exchange / Box Spread)")
    print("  Core constraint: C - P = S - K·e^(-rT)  (Put-Call Parity)")
    print("  Box spread: payoff = K2 - K1, cost should = (K2-K1)·e^(-rT)")

    from polymarket_arbitrage.adapters.options import generate_demo_data, detect

    instruments, spot_prices = generate_demo_data()
    opps = detect(instruments, spot_prices)

    parity = [o for o in opps if "overpriced" in o.description.lower() and "Box" not in o.description]
    cross_ex = [o for o in opps if "Cross-exchange" in o.description]
    box = [o for o in opps if "Box" in o.description]

    section(f"Put-Call Parity violations: {len(parity)} opportunities")
    for o in parity:
        print(f"    {o.description}")
        print(f"           net profit: ${o.net_profit:.2f}")

    section(f"Cross-exchange mispricing: {len(cross_ex)} opportunities")
    for o in cross_ex:
        print(f"    {o.description}")
        print(f"           net profit: ${o.net_profit:.2f}")

    section(f"Box spread arbs: {len(box)} opportunities")
    for o in box:
        print(f"    {o.description}")
        print(f"           net profit: ${o.net_profit:.2f}")

    return len(opps)


def main() -> None:
    print("=" * 70)
    print("  MULTI-DOMAIN ARBITRAGE DETECTION")
    print("  Core logic: arXiv:2508.03474 generalised")
    print("=" * 70)
    print("""
  The paper's insight:
    "When related prices violate a known constraint,
     guaranteed profit exists."

  This principle applies universally:
    Prediction markets : sum(outcome_prices) = 1
    Sports betting     : sum(1/odds) = 1 (cross-book)
    DeFi               : same_asset_same_price + triangle = 1
    Options            : C - P = S - K·e^(-rT)
""")

    t0 = time.time()
    totals = {}

    totals["Prediction Markets"] = run_prediction_markets()
    totals["Sports Betting"] = run_sports_betting()
    totals["DeFi"] = run_defi()
    totals["Options"] = run_options()

    elapsed = time.time() - t0

    # Summary
    header("SUMMARY")
    total = sum(totals.values())
    for domain, count in totals.items():
        bar = "#" * count
        print(f"    {domain:22s}: {count:3d} opportunities  {bar}")
    print(f"\n    {'TOTAL':22s}: {total:3d} opportunities")
    print(f"    Elapsed: {elapsed:.2f}s")

    print("""
  Key takeaway:
    The same constraint-violation framework from the Polymarket paper
    detects arbitrage across ALL four domains. The math is identical —
    only the data sources and fee structures differ.
""")


if __name__ == "__main__":
    main()
