"""Main arbitrage detection pipeline.

Implements the paper's multi-stage approach:
  Stage 1: Fetch market data from Polymarket Gamma API
  Stage 2: Intra-market arbitrage detection
    - Single-condition: YES + NO != $1
    - NegRisk multi-condition: sum(YES_i) != $1
  Stage 3: Combinatorial arbitrage detection
    - Step 3a: Temporal filtering
    - Step 3b: Topic classification via embeddings
    - Step 3c: Semantic similarity to find related market pairs
    - Step 3d: LLM-based relationship extraction
    - Step 3e: Arbitrage detection on related pairs
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

from polymarket_arbitrage.api.gamma_client import GammaClient
from polymarket_arbitrage.arbitrage.combinatorial import detect_combinatorial_arbitrage
from polymarket_arbitrage.arbitrage.intra_market import detect_all_intra_market
from polymarket_arbitrage.models.market import (
    ArbitrageOpportunity,
    Event,
    MarketRelationship,
)

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Results from a full pipeline run."""
    events: list[Event] = field(default_factory=list)
    intra_market_opportunities: list[ArbitrageOpportunity] = field(default_factory=list)
    relationships: list[MarketRelationship] = field(default_factory=list)
    combinatorial_opportunities: list[ArbitrageOpportunity] = field(default_factory=list)

    @property
    def all_opportunities(self) -> list[ArbitrageOpportunity]:
        return self.intra_market_opportunities + self.combinatorial_opportunities

    @property
    def total_markets(self) -> int:
        return sum(len(e.markets) for e in self.events)


async def run_pipeline(
    *,
    max_events: Optional[int] = None,
    skip_combinatorial: bool = False,
    similarity_threshold: float = 0.75,
    max_llm_pairs: int = 100,
) -> PipelineResult:
    """Run the full arbitrage detection pipeline.

    Args:
        max_events: Cap on number of events to fetch (None = all).
        skip_combinatorial: If True, skip the combinatorial stage
            (useful when no LLM API key or embedding model is available).
        similarity_threshold: Cosine similarity threshold for related markets.
        max_llm_pairs: Max number of market pairs to send to the LLM.
    """
    result = PipelineResult()

    # ------------------------------------------------------------------
    # Stage 1: Fetch data
    # ------------------------------------------------------------------
    logger.info("Stage 1: Fetching market data from Polymarket...")
    async with GammaClient() as client:
        result.events = await client.fetch_all_events(
            active=True,
            max_events=max_events,
        )
    logger.info(
        "Fetched %d events with %d total markets",
        len(result.events), result.total_markets,
    )

    if not result.events:
        logger.warning("No events fetched; pipeline complete.")
        return result

    # ------------------------------------------------------------------
    # Stage 2: Intra-market arbitrage
    # ------------------------------------------------------------------
    logger.info("Stage 2: Detecting intra-market arbitrage...")
    result.intra_market_opportunities = detect_all_intra_market(result.events)
    logger.info(
        "Found %d intra-market opportunities",
        len(result.intra_market_opportunities),
    )

    if skip_combinatorial:
        logger.info("Skipping combinatorial stage (--skip-combinatorial).")
        return result

    # ------------------------------------------------------------------
    # Stage 3: Combinatorial arbitrage
    # ------------------------------------------------------------------
    logger.info("Stage 3: Detecting combinatorial arbitrage...")
    all_markets = [m for e in result.events for m in e.markets]

    # Step 3a: Temporal filtering
    from polymarket_arbitrage.nlp.embeddings import filter_temporal_proximity
    temporal_pairs = filter_temporal_proximity(all_markets)
    logger.info("Step 3a: %d temporally proximate pairs", len(temporal_pairs))

    # Step 3b: Topic classification
    from polymarket_arbitrage.nlp.embeddings import classify_topics
    topic_groups = classify_topics(all_markets)

    # Step 3c: Find semantically similar markets within each topic
    from polymarket_arbitrage.nlp.embeddings import find_related_markets
    related_pairs: list[tuple] = []
    for topic, topic_markets in topic_groups.items():
        if len(topic_markets) < 2:
            continue
        pairs = find_related_markets(topic_markets, threshold=similarity_threshold)
        related_pairs.extend(pairs)
        logger.info("Step 3c: Topic '%s' -> %d related pairs", topic, len(pairs))

    logger.info("Step 3c total: %d related market pairs", len(related_pairs))

    # Step 3d: LLM relationship extraction
    from polymarket_arbitrage.nlp.relationship import extract_relationships_batch
    result.relationships = extract_relationships_batch(
        related_pairs, max_pairs=max_llm_pairs,
    )
    logger.info("Step 3d: %d relationships extracted", len(result.relationships))

    # Step 3e: Detect combinatorial arbitrage
    result.combinatorial_opportunities = detect_combinatorial_arbitrage(
        result.relationships,
    )
    logger.info(
        "Step 3e: %d combinatorial opportunities",
        len(result.combinatorial_opportunities),
    )

    return result


def run_pipeline_sync(**kwargs) -> PipelineResult:
    """Synchronous wrapper for the pipeline."""
    return asyncio.run(run_pipeline(**kwargs))
