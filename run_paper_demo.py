#!/usr/bin/env python3
"""Paper-faithful demo: Full pipeline from arXiv:2508.03474.

Reproduces the key scenarios from "Unravelling the Probabilistic Forest:
Arbitrage in Prediction Markets" (Saguillo et al., AFT 2025).

This script:
1. Creates ~40 markets across 7 topics matching the paper's dataset profile
2. Runs the FULL pipeline: temporal filter -> topic classification (embeddings)
   -> semantic similarity -> relationship extraction -> arbitrage detection
3. Reports results with paper-referenced explanations

The paper found:
- $10.58M from single-condition rebalancing (sports longs dominant)
- $28.9M from NegRisk intra-market arbitrage (election NO-buying)
- ~$95K from combinatorial arbitrage (popular vote vs presidency)
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta, timezone

from polymarket_arbitrage.models.market import (
    ArbitrageOpportunity,
    ArbitrageType,
    Event,
    Market,
    MarketRelationship,
    MarketStatus,
    Token,
)
from polymarket_arbitrage.arbitrage.intra_market import detect_all_intra_market
from polymarket_arbitrage.arbitrage.combinatorial import detect_combinatorial_arbitrage
from polymarket_arbitrage.nlp.embeddings import (
    classify_topics,
    find_related_markets,
    filter_temporal_proximity,
)
from polymarket_arbitrage.reporting import summarize


# ======================================================================
# Synthetic dataset mirroring paper's market distribution
# ======================================================================

def _m(
    id: str, question: str, yes: float, no: float,
    end_date: datetime | None = None, desc: str = "",
) -> Market:
    return Market(
        id=id, question=question, condition_id=f"cond_{id}",
        slug=id,
        tokens=[
            Token(token_id=f"{id}_y", outcome="Yes", price=yes),
            Token(token_id=f"{id}_n", outcome="No", price=no),
        ],
        status=MarketStatus.ACTIVE, volume=500_000, liquidity=100_000,
        end_date=end_date, description=desc,
    )


def build_paper_dataset() -> list[Event]:
    """Build dataset mimicking the paper's Polymarket snapshot.

    The paper analyzed 10,237 markets (17,218 conditions) over
    April 2024 - April 2025. We create a representative subset.
    """
    now = datetime.now(timezone.utc)
    d7 = now + timedelta(days=7)
    d30 = now + timedelta(days=30)
    d90 = now + timedelta(days=90)
    d180 = now + timedelta(days=180)

    events: list[Event] = []

    # ==================================================================
    # POLITICS — Paper found $28.9M in NegRisk election arbitrage
    # ==================================================================

    # NegRisk: 2024 Presidential Election Winner (paper's primary example)
    events.append(Event(
        id="pol_1", title="2024 Presidential Election Winner",
        slug="2024-pres-winner", neg_risk=True,
        description="Who will win the 2024 US Presidential Election?",
        markets=[
            _m("pol_1a", "Will Donald Trump win the 2024 Presidential Election?",
               0.55, 0.45, d30),
            _m("pol_1b", "Will Kamala Harris win the 2024 Presidential Election?",
               0.43, 0.57, d30),
            _m("pol_1c", "Will a third-party candidate win the 2024 Presidential Election?",
               0.04, 0.96, d30),
            # sum(YES) = 0.55 + 0.43 + 0.04 = 1.02 → SHORT arb (paper's election NO-buy)
        ],
    ))

    # NegRisk: Popular vote winner
    events.append(Event(
        id="pol_2", title="2024 Popular Vote Winner",
        slug="2024-popular-vote", neg_risk=True,
        description="Who will win the 2024 popular vote?",
        markets=[
            _m("pol_2a", "Will the Republican candidate win the 2024 popular vote?",
               0.38, 0.62, d30,
               "Resolves YES if Republican wins the national popular vote count."),
            _m("pol_2b", "Will the Democratic candidate win the 2024 popular vote?",
               0.58, 0.42, d30,
               "Resolves YES if Democrat wins the national popular vote count."),
            _m("pol_2c", "Will a third party win the 2024 popular vote?",
               0.01, 0.99, d30),
            # sum(YES) = 0.38 + 0.58 + 0.01 = 0.97 → LONG arb
        ],
    ))

    # Electoral margin — combinatorial with presidency
    events.append(Event(
        id="pol_3", title="2024 Electoral College Margin",
        slug="2024-ec-margin",
        markets=[
            _m("pol_3a", "Will the 2024 presidential winner win by more than 100 electoral votes?",
               0.35, 0.65, d30,
               "Resolves YES if winning margin in electoral college > 100."),
        ],
    ))

    # Senate control — related to presidency
    events.append(Event(
        id="pol_4", title="2024 Senate Control",
        slug="2024-senate", neg_risk=True,
        markets=[
            _m("pol_4a", "Will Republicans control the Senate after 2024 elections?",
               0.62, 0.38, d30),
            _m("pol_4b", "Will Democrats control the Senate after 2024 elections?",
               0.36, 0.64, d30),
            # sum = 0.98 → LONG arb (small)
        ],
    ))

    # Swing state — subset of presidential winner
    events.append(Event(
        id="pol_5", title="Pennsylvania 2024",
        slug="pa-2024",
        markets=[
            _m("pol_5a", "Will Trump win Pennsylvania in the 2024 Presidential Election?",
               0.52, 0.48, d30,
               "Resolves YES if Trump wins PA. PA is a key swing state."),
        ],
    ))

    # ==================================================================
    # SPORTS — Paper found $10.58M in single-condition rebalancing
    # ==================================================================

    # NegRisk: World Cup
    events.append(Event(
        id="spt_1", title="2026 FIFA World Cup Winner",
        slug="wc-2026-winner", neg_risk=True,
        markets=[
            _m("spt_1a", "Will Brazil win the 2026 FIFA World Cup?", 0.15, 0.85, d180),
            _m("spt_1b", "Will France win the 2026 FIFA World Cup?", 0.13, 0.87, d180),
            _m("spt_1c", "Will Argentina win the 2026 FIFA World Cup?", 0.18, 0.82, d180),
            _m("spt_1d", "Will England win the 2026 FIFA World Cup?", 0.09, 0.91, d180),
            _m("spt_1e", "Will Germany win the 2026 FIFA World Cup?", 0.08, 0.92, d180),
            _m("spt_1f", "Will Spain win the 2026 FIFA World Cup?", 0.10, 0.90, d180),
            _m("spt_1g", "Will another country win the 2026 FIFA World Cup?", 0.18, 0.82, d180),
            # sum(YES) = 0.91 → LONG arb (paper: sports longs dominant)
        ],
    ))

    # Single-condition sports with mispricing
    events.append(Event(
        id="spt_2", title="NFL Super Bowl 2026",
        slug="nfl-sb-2026",
        markets=[
            _m("spt_2a", "Will the Kansas City Chiefs win the 2026 Super Bowl?",
               0.12, 0.82, d90),  # sum=0.94 → LONG
        ],
    ))

    events.append(Event(
        id="spt_3", title="NBA Finals MVP 2025",
        slug="nba-finals-mvp",
        markets=[
            _m("spt_3a", "Will Luka Doncic win the 2025 NBA Finals MVP?",
               0.30, 0.74, d7),  # sum=1.04 → SHORT
        ],
    ))

    # Champions League
    events.append(Event(
        id="spt_4", title="Champions League Winner 2025",
        slug="ucl-2025", neg_risk=True,
        markets=[
            _m("spt_4a", "Will Real Madrid win the 2025 Champions League?", 0.25, 0.75, d30),
            _m("spt_4b", "Will Manchester City win the 2025 Champions League?", 0.20, 0.80, d30),
            _m("spt_4c", "Will Barcelona win the 2025 Champions League?", 0.18, 0.82, d30),
            _m("spt_4d", "Will Bayern Munich win the 2025 Champions League?", 0.12, 0.88, d30),
            _m("spt_4e", "Will another club win the 2025 Champions League?", 0.20, 0.80, d30),
            # sum = 0.95 → LONG
        ],
    ))

    # ==================================================================
    # CRYPTO
    # ==================================================================

    events.append(Event(
        id="cry_1", title="Bitcoin Price End of 2026",
        slug="btc-eoy-2026", neg_risk=True,
        markets=[
            _m("cry_1a", "Will Bitcoin be above $150,000 on December 31, 2026?",
               0.20, 0.80, d180),
            _m("cry_1b", "Will Bitcoin be between $100,000 and $150,000 on December 31, 2026?",
               0.35, 0.65, d180),
            _m("cry_1c", "Will Bitcoin be between $50,000 and $100,000 on December 31, 2026?",
               0.30, 0.70, d180),
            _m("cry_1d", "Will Bitcoin be below $50,000 on December 31, 2026?",
               0.10, 0.90, d180),
            # sum = 0.95 → LONG
        ],
    ))

    events.append(Event(
        id="cry_2", title="Ethereum Price Milestone",
        slug="eth-milestone",
        markets=[
            _m("cry_2a", "Will Ethereum reach $10,000 in 2026?",
               0.15, 0.80, d180),  # sum=0.95 → LONG
        ],
    ))

    # Cross-market: ETH flippening vs ETH price — complement-like
    events.append(Event(
        id="cry_3", title="ETH Flippening",
        slug="eth-flippening",
        markets=[
            _m("cry_3a", "Will Ethereum's market cap exceed Bitcoin's market cap in 2026?",
               0.05, 0.92, d180,
               "Resolves YES if ETH market cap > BTC market cap at any point."),
        ],
    ))

    # ==================================================================
    # ECONOMY — Paper found complement arbs in inflation/Fed markets
    # ==================================================================

    events.append(Event(
        id="eco_1", title="Fed Rate Decision June 2026",
        slug="fed-june-2026",
        markets=[
            _m("eco_1a", "Will the Federal Reserve cut interest rates in June 2026?",
               0.55, 0.40, d90),  # sum=0.95, but note this → could pair with eco_2
        ],
    ))

    events.append(Event(
        id="eco_2", title="Fed Rate Decision July 2026",
        slug="fed-july-2026",
        markets=[
            _m("eco_2a", "Will the Federal Reserve cut interest rates in July 2026?",
               0.48, 0.47, d90),  # sum=0.95
        ],
    ))

    # Inflation above/below — complement pair
    events.append(Event(
        id="eco_3", title="US Inflation Above 3%",
        slug="cpi-above-3",
        markets=[
            _m("eco_3a", "Will US CPI year-over-year inflation exceed 3% in December 2026?",
               0.30, 0.70, d180,
               "Resolves YES if December 2026 CPI YoY > 3%."),
        ],
    ))

    events.append(Event(
        id="eco_4", title="US Inflation Below 3%",
        slug="cpi-below-3",
        markets=[
            _m("eco_4a", "Will US CPI year-over-year inflation be at or below 3% in December 2026?",
               0.62, 0.38, d180,
               "Resolves YES if December 2026 CPI YoY <= 3%."),
            # eco_3a.YES + eco_4a.YES = 0.30 + 0.62 = 0.92 → complement LONG arb
        ],
    ))

    # Recession market
    events.append(Event(
        id="eco_5", title="US Recession 2026",
        slug="us-recession-2026",
        markets=[
            _m("eco_5a", "Will the US enter a recession in 2026?",
               0.18, 0.82, d180),
        ],
    ))

    # ==================================================================
    # TECHNOLOGY
    # ==================================================================

    events.append(Event(
        id="tch_1", title="AI Regulation",
        slug="ai-regulation",
        markets=[
            _m("tch_1a", "Will the US pass federal AI regulation legislation in 2026?",
               0.25, 0.70, d180),  # sum=0.95
        ],
    ))

    events.append(Event(
        id="tch_2", title="Apple AI Product",
        slug="apple-ai",
        markets=[
            _m("tch_2a", "Will Apple release a standalone AI hardware device in 2026?",
               0.10, 0.88, d180),
        ],
    ))

    # ==================================================================
    # TWITTER / SOCIAL
    # ==================================================================

    events.append(Event(
        id="twt_1", title="Twitter/X Monthly Users",
        slug="x-users",
        markets=[
            _m("twt_1a", "Will X (Twitter) reach 1 billion monthly active users by end of 2026?",
               0.08, 0.90, d180),
        ],
    ))

    # ==================================================================
    # CULTURE
    # ==================================================================

    events.append(Event(
        id="cul_1", title="Oscar Best Picture 2026",
        slug="oscar-2026", neg_risk=True,
        markets=[
            _m("cul_1a", "Will an AI-generated film win Best Picture at the 2026 Oscars?",
               0.02, 0.98, d90),
            _m("cul_1b", "Will a Marvel film win Best Picture at the 2026 Oscars?",
               0.05, 0.95, d90),
            _m("cul_1c", "Will another film win Best Picture at the 2026 Oscars?",
               0.90, 0.10, d90),
            # sum = 0.97 → LONG
        ],
    ))

    return events


# ======================================================================
# Full pipeline execution
# ======================================================================

def run_full_pipeline(events: list[Event]) -> None:
    all_markets = [m for e in events for m in e.markets]
    total_conditions = sum(len(e.markets) for e in events)

    print("=" * 70)
    print("PAPER REPRODUCTION: arXiv:2508.03474")
    print("'Unravelling the Probabilistic Forest'")
    print("Saguillo, Ghafouri, Kiffer, Suarez-Tangil (AFT 2025)")
    print("=" * 70)
    print(f"\nDataset: {len(events)} events, {total_conditions} conditions, "
          f"{len(all_markets)} markets")
    print(f"(Paper analyzed 10,237 markets / 17,218 conditions)\n")

    # ------------------------------------------------------------------
    # STAGE 1: Intra-market arbitrage (paper Sections 4.1-4.2)
    # ------------------------------------------------------------------
    print("-" * 70)
    print("STAGE 1: Intra-Market Arbitrage Detection")
    print("  Paper ref: Section 4 — Market Rebalancing Arbitrage")
    print("-" * 70)

    t0 = time.time()
    intra_opps = detect_all_intra_market(events)
    t1 = time.time()

    single = [o for o in intra_opps if o.arb_type == ArbitrageType.SINGLE_CONDITION]
    negrisk = [o for o in intra_opps if o.arb_type == ArbitrageType.NEGRISK_INTRA]

    print(f"\n  Single-condition arbitrage: {len(single)} opportunities")
    for o in single:
        dir_label = "BUY all" if o.direction.value == "long" else "SELL all"
        print(f"    [{dir_label}] {o.markets[0].question[:60]}")
        print(f"      YES={o.markets[0].yes_price:.2f} + NO={o.markets[0].no_price:.2f}"
              f" = {o.price_sum:.2f}  =>  net profit: ${o.net_profit_per_dollar:.4f}/dollar")

    print(f"\n  NegRisk intra-event arbitrage: {len(negrisk)} opportunities")
    for o in negrisk:
        dir_label = "BUY all YES" if o.direction.value == "long" else "SELL YES / BUY NO"
        event_title = o.events[0].title if o.events else "?"
        print(f"    [{dir_label}] {event_title}")
        print(f"      sum(YES) = {o.price_sum:.2f} across {len(o.markets)} markets"
              f"  =>  net profit: ${o.net_profit_per_dollar:.4f}/dollar")

    print(f"\n  Time: {t1-t0:.3f}s")

    # ------------------------------------------------------------------
    # STAGE 2: Combinatorial pipeline (paper Section 5)
    # ------------------------------------------------------------------
    print("\n" + "-" * 70)
    print("STAGE 2: Combinatorial Arbitrage Pipeline")
    print("  Paper ref: Section 5 — Combinatorial Arbitrage")
    print("-" * 70)

    # Step 2a: Temporal filtering
    print("\n  Step 2a: Temporal Filtering")
    print(f"    Paper: filter markets with overlapping resolution windows")
    t0 = time.time()
    temporal_pairs = filter_temporal_proximity(all_markets, max_days=30)
    t1 = time.time()
    print(f"    Found {len(temporal_pairs)} temporally proximate pairs ({t1-t0:.3f}s)")

    # Step 2b: Topic classification via embeddings
    print("\n  Step 2b: Topic Classification (Embedding Cosine Similarity)")
    print(f"    Paper: uses Linq-Embed-Mistral; we use all-MiniLM-L6-v2")
    print(f"    Paper achieved 92% topic classification accuracy")
    t0 = time.time()
    topic_groups = classify_topics(all_markets)
    t1 = time.time()

    print(f"    Classification results ({t1-t0:.3f}s):")
    for topic, mlist in sorted(topic_groups.items(), key=lambda x: -len(x[1])):
        if mlist:
            examples = ", ".join(m.question[:45] + "..." for m in mlist[:2])
            print(f"      {topic:12s}: {len(mlist):2d} markets  (e.g. {examples})")

    # Step 2c: Semantic similarity within topics
    print("\n  Step 2c: Semantic Similarity Search (Related Market Discovery)")
    print(f"    Paper: O(2^(n+m)) naive -> heuristic reduction via embeddings")
    t0 = time.time()
    related_pairs = []
    for topic, topic_markets in topic_groups.items():
        if len(topic_markets) < 2:
            continue
        pairs = find_related_markets(topic_markets, threshold=0.45)
        related_pairs.extend(pairs)
    t1 = time.time()

    print(f"    Found {len(related_pairs)} related pairs (threshold=0.45, {t1-t0:.3f}s)")
    print(f"    Top similar pairs:")
    for ma, mb, score in sorted(related_pairs, key=lambda x: -x[2])[:8]:
        print(f"      [{score:.3f}] '{ma.question[:40]}...' <-> '{mb.question[:40]}...'")

    # Step 2d: Relationship extraction
    # (In production this uses LLM; here we use rule-based heuristics
    # matching the paper's relationship types)
    print("\n  Step 2d: Relationship Extraction")
    print(f"    Paper: uses DeepSeek-R1-Distill-Qwen-32B for resolution vectors")
    print(f"    Demo: using rule-based heuristics (no LLM API needed)")

    relationships = _extract_known_relationships(events, related_pairs)
    print(f"    Extracted {len(relationships)} logical relationships:")
    for rel in relationships:
        print(f"      [{rel.relationship_type}] (conf={rel.confidence:.2f}) "
              f"'{rel.market_a.question[:35]}...' <-> '{rel.market_b.question[:35]}...'")
        if rel.resolution_vectors:
            print(f"        Resolution vectors: {rel.resolution_vectors}")

    # Step 2e: Combinatorial arbitrage detection
    print("\n  Step 2e: Combinatorial Arbitrage Detection")
    combo_opps = detect_combinatorial_arbitrage(relationships)
    print(f"    Found {len(combo_opps)} combinatorial opportunities:")
    for o in combo_opps:
        print(f"    [{o.direction.value.upper()}] {o.description[:80]}...")
        print(f"      Net profit: ${o.net_profit_per_dollar:.4f}/dollar")

    # ------------------------------------------------------------------
    # FINAL REPORT
    # ------------------------------------------------------------------
    all_opps = intra_opps + combo_opps
    print("\n")
    print(summarize(all_opps))

    # Paper comparison
    print("\n" + "=" * 70)
    print("COMPARISON WITH PAPER FINDINGS")
    print("=" * 70)
    print("""
  Paper (April 2024 - April 2025, 10,237 markets):
    Single-condition rebalancing:  $10.58M realized profit
    NegRisk intra-market:          $28.90M realized profit
    Combinatorial:                 $0.095M realized profit (~$95K)
    Total:                         ~$40M

  Key insight: 41% of conditions (7,051/17,218) exhibited at least
  one arbitrage opportunity. Median profit ~$0.60 per dollar.

  Our demo ({n_events} events, {n_markets} markets):
    Single-condition:  {n_single} opportunities detected
    NegRisk:           {n_neg} opportunities detected
    Combinatorial:     {n_combo} opportunities detected
    Total:             {n_total} opportunities
""".format(
        n_events=len(events),
        n_markets=len(all_markets),
        n_single=len(single),
        n_neg=len(negrisk),
        n_combo=len(combo_opps),
        n_total=len(all_opps),
    ))


def _extract_known_relationships(
    events: list[Event],
    related_pairs: list[tuple[Market, Market, float]],
) -> list[MarketRelationship]:
    """Rule-based relationship extraction for demo.

    In the full pipeline, the LLM generates resolution vectors.
    Here we identify known logical relationships from our synthetic data.
    """
    m = {market.id: market for e in events for market in e.markets}
    rels: list[MarketRelationship] = []

    # Complement: inflation above 3% vs at/below 3%
    if "eco_3a" in m and "eco_4a" in m:
        rels.append(MarketRelationship(
            market_a=m["eco_3a"], market_b=m["eco_4a"],
            relationship_type="complement", confidence=0.98,
            description="CPI > 3% and CPI <= 3% are exhaustive and mutually exclusive",
            resolution_vectors=[[1, 0], [0, 1]],
        ))

    # Subset: winning PA implies winning presidency (usually)
    if "pol_5a" in m and "pol_1a" in m:
        rels.append(MarketRelationship(
            market_a=m["pol_5a"], market_b=m["pol_1a"],
            relationship_type="overlapping", confidence=0.80,
            description="Winning Pennsylvania is strongly correlated with winning presidency",
            resolution_vectors=[[0, 0], [0, 1], [1, 1]],
            # Note: [1,0] (win PA but lose presidency) is very unlikely but possible
        ))

    # Mutually exclusive: Republican popular vote vs Democratic popular vote
    if "pol_2a" in m and "pol_2b" in m:
        rels.append(MarketRelationship(
            market_a=m["pol_2a"], market_b=m["pol_2b"],
            relationship_type="mutually_exclusive", confidence=0.95,
            description="Only one party can win the popular vote",
            resolution_vectors=[[0, 0], [0, 1], [1, 0]],
        ))

    # Correlated: Fed rate cuts in consecutive months
    if "eco_1a" in m and "eco_2a" in m:
        rels.append(MarketRelationship(
            market_a=m["eco_1a"], market_b=m["eco_2a"],
            relationship_type="overlapping", confidence=0.70,
            description="Consecutive Fed rate decisions are correlated",
            resolution_vectors=[[0, 0], [0, 1], [1, 0], [1, 1]],
        ))

    # Also try to find relationships from embedding similarity pairs
    # that we might have missed
    seen = {(r.market_a.id, r.market_b.id) for r in rels}
    for ma, mb, score in related_pairs:
        key = (ma.id, mb.id)
        rev = (mb.id, ma.id)
        if key in seen or rev in seen:
            continue
        # High similarity but different events → candidate for relationship
        if score > 0.7 and ma.id.split("_")[0] != mb.id.split("_")[0]:
            # Skip if same event
            rels.append(MarketRelationship(
                market_a=ma, market_b=mb,
                relationship_type="overlapping", confidence=score,
                description=f"High semantic similarity ({score:.3f}) detected by embeddings",
                resolution_vectors=[[0, 0], [0, 1], [1, 0], [1, 1]],
            ))
            seen.add(key)

    return rels


if __name__ == "__main__":
    events = build_paper_dataset()
    run_full_pipeline(events)
