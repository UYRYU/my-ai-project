#!/usr/bin/env python3
"""Polymarket Arbitrage Detector.

Implementation of "Unravelling the Probabilistic Forest:
Arbitrage in Prediction Markets" (Saguillo et al., AFT 2025).

Detects two types of arbitrage on Polymarket:
  1. Intra-market: price deviations within single conditions or NegRisk events
  2. Combinatorial: cross-market arbitrage using semantic relationship detection

Usage:
  python main.py                    # Run with demo data
  python main.py --live             # Fetch live data from Polymarket
  python main.py --live --max-events 50  # Limit to 50 events
  python main.py --json             # Output as JSON
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from polymarket_arbitrage.arbitrage.combinatorial import detect_combinatorial_arbitrage
from polymarket_arbitrage.arbitrage.intra_market import detect_all_intra_market
from polymarket_arbitrage.models.market import ArbitrageOpportunity, Event
from polymarket_arbitrage.reporting import summarize, to_json_serializable


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def run_demo() -> tuple[list[Event], list[ArbitrageOpportunity]]:
    """Run arbitrage detection on synthetic demo data."""
    from polymarket_arbitrage.demo import generate_demo_events

    events = generate_demo_events()
    print(f"Loaded {len(events)} demo events with "
          f"{sum(len(e.markets) for e in events)} markets\n")

    # Intra-market detection
    intra_opps = detect_all_intra_market(events)

    # For demo, simulate combinatorial detection without LLM
    # by manually checking known related pairs
    from polymarket_arbitrage.models.market import MarketRelationship
    relationships: list[MarketRelationship] = []

    # Find the known related pairs in demo data
    markets_by_id = {m.id: m for e in events for m in e.markets}

    # m6 (Republican popular vote) is related to m7 (Republican presidency)
    if "m6" in markets_by_id and "m7" in markets_by_id:
        relationships.append(MarketRelationship(
            market_a=markets_by_id["m6"],
            market_b=markets_by_id["m7"],
            relationship_type="overlapping",
            confidence=0.85,
            description="Winning the popular vote is correlated with winning the presidency",
            resolution_vectors=[[0, 0], [0, 1], [1, 0], [1, 1]],
        ))

    # m8 (inflation >3%) is complement of m9 (inflation <=3%)
    if "m8" in markets_by_id and "m9" in markets_by_id:
        relationships.append(MarketRelationship(
            market_a=markets_by_id["m8"],
            market_b=markets_by_id["m9"],
            relationship_type="complement",
            confidence=0.95,
            description="CPI > 3% and CPI <= 3% are exhaustive and mutually exclusive",
            resolution_vectors=[[1, 0], [0, 1]],
        ))

    combo_opps = detect_combinatorial_arbitrage(relationships)
    all_opps = intra_opps + combo_opps
    return events, all_opps


async def run_live(
    max_events: int | None = None,
    skip_combinatorial: bool = False,
    similarity_threshold: float = 0.75,
    max_llm_pairs: int = 100,
) -> tuple[list[Event], list[ArbitrageOpportunity]]:
    """Run arbitrage detection on live Polymarket data."""
    from polymarket_arbitrage.pipeline import run_pipeline

    result = await run_pipeline(
        max_events=max_events,
        skip_combinatorial=skip_combinatorial,
        similarity_threshold=similarity_threshold,
        max_llm_pairs=max_llm_pairs,
    )
    return result.events, result.all_opportunities


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Polymarket Arbitrage Detector — "
        "Implementation of 'Unravelling the Probabilistic Forest' (Saguillo et al., 2025)",
    )
    parser.add_argument(
        "--live", action="store_true",
        help="Fetch live data from Polymarket Gamma API (default: use demo data)",
    )
    parser.add_argument(
        "--max-events", type=int, default=None,
        help="Maximum number of events to fetch in live mode",
    )
    parser.add_argument(
        "--skip-combinatorial", action="store_true",
        help="Skip combinatorial arbitrage detection (no embeddings/LLM needed)",
    )
    parser.add_argument(
        "--similarity-threshold", type=float, default=0.75,
        help="Cosine similarity threshold for related market pairs (default: 0.75)",
    )
    parser.add_argument(
        "--max-llm-pairs", type=int, default=100,
        help="Max number of market pairs to analyze with LLM (default: 100)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output results as JSON",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    setup_logging(args.verbose)

    if args.live:
        events, opportunities = asyncio.run(run_live(
            max_events=args.max_events,
            skip_combinatorial=args.skip_combinatorial,
            similarity_threshold=args.similarity_threshold,
            max_llm_pairs=args.max_llm_pairs,
        ))
    else:
        events, opportunities = run_demo()

    if args.json:
        output = {
            "events_count": len(events),
            "markets_count": sum(len(e.markets) for e in events),
            "opportunities": to_json_serializable(opportunities),
        }
        print(json.dumps(output, indent=2))
    else:
        print(summarize(opportunities))


if __name__ == "__main__":
    main()
