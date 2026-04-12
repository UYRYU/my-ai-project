"""LLM-based logical relationship extraction between markets.

The paper uses DeepSeek-R1-Distill-Qwen-32B to:
1. Analyze pairs of market questions/descriptions
2. Extract logical relationships (subset, complement, mutually exclusive, etc.)
3. Generate resolution vectors capturing the state space of possible resolutions

We use the Anthropic Claude API as the LLM backend (configurable).
The prompt follows the paper's approach: explain the task, define rules,
restrict output to structured JSON, and provide an example.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from polymarket_arbitrage.models.market import Market, MarketRelationship

logger = logging.getLogger(__name__)

RELATIONSHIP_PROMPT = """\
You are an expert at analyzing prediction markets. Given two prediction market \
questions, determine their logical relationship.

## Task
Analyze the two market questions below and determine:
1. **relationship_type**: One of:
   - "subset": Market A's YES outcome implies Market B's YES outcome (A ⊂ B)
   - "superset": Market B's YES outcome implies Market A's YES outcome (A ⊃ B)
   - "complement": A YES in one implies NO in the other (mutually exclusive and exhaustive)
   - "mutually_exclusive": Both cannot be YES simultaneously, but both can be NO
   - "overlapping": Outcomes are partially correlated but not strictly linked
   - "independent": No logical relationship
2. **confidence**: Your confidence in this assessment (0.0 to 1.0)
3. **explanation**: Brief explanation of the relationship
4. **resolution_vectors**: List of all possible [A_outcome, B_outcome] pairs where \
each outcome is 0 (NO) or 1 (YES). Only include logically possible combinations.

## Rules
- Consider ONLY the logical/semantic relationship, not current prices.
- "subset" means if A resolves YES, then B MUST also resolve YES.
- "complement" means exactly one of A or B will resolve YES.
- Be conservative: if uncertain, choose "independent".

## Market A
Question: {question_a}
Description: {description_a}

## Market B
Question: {question_b}
Description: {description_b}

## Output
Respond with ONLY a JSON object (no markdown, no extra text):
{{"relationship_type": "...", "confidence": 0.0, "explanation": "...", "resolution_vectors": [[0,0],[0,1],[1,0],[1,1]]}}
"""


def _call_llm(prompt: str) -> Optional[dict[str, Any]]:
    """Call the LLM and parse JSON response."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set; skipping LLM relationship extraction")
        return None

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        # Extract JSON from response (handle potential markdown wrapping)
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        return json.loads(text)
    except Exception as e:
        logger.error("LLM call failed: %s", e)
        return None


def extract_relationship(
    market_a: Market,
    market_b: Market,
) -> Optional[MarketRelationship]:
    """Use LLM to extract the logical relationship between two markets.

    Returns a MarketRelationship if a non-independent relationship is found,
    or None if the markets are independent or the LLM call fails.
    """
    prompt = RELATIONSHIP_PROMPT.format(
        question_a=market_a.question,
        description_a=market_a.description or "(no description)",
        question_b=market_b.question,
        description_b=market_b.description or "(no description)",
    )

    result = _call_llm(prompt)
    if result is None:
        return None

    rel_type = result.get("relationship_type", "independent")
    confidence = float(result.get("confidence", 0.0))

    if rel_type == "independent":
        return None

    # Filter low-confidence results
    if confidence < 0.5:
        logger.debug(
            "Low confidence (%.2f) for %s <-> %s, skipping",
            confidence, market_a.question[:50], market_b.question[:50],
        )
        return None

    vectors = result.get("resolution_vectors")

    return MarketRelationship(
        market_a=market_a,
        market_b=market_b,
        relationship_type=rel_type,
        confidence=confidence,
        description=result.get("explanation", ""),
        resolution_vectors=vectors,
    )


def extract_relationships_batch(
    market_pairs: list[tuple[Market, Market, float]],
    max_pairs: int = 100,
) -> list[MarketRelationship]:
    """Extract relationships for a batch of candidate market pairs.

    The pairs should be pre-filtered by embedding similarity (from embeddings.py).
    We cap the number of LLM calls for cost control.
    """
    relationships: list[MarketRelationship] = []
    pairs_to_process = market_pairs[:max_pairs]

    logger.info(
        "Extracting relationships for %d market pairs (capped at %d)",
        len(market_pairs), max_pairs,
    )

    for market_a, market_b, sim_score in pairs_to_process:
        rel = extract_relationship(market_a, market_b)
        if rel is not None:
            relationships.append(rel)
            logger.info(
                "Found %s relationship (conf=%.2f): '%s' <-> '%s'",
                rel.relationship_type,
                rel.confidence,
                market_a.question[:50],
                market_b.question[:50],
            )

    logger.info(
        "Extracted %d relationships from %d pairs",
        len(relationships), len(pairs_to_process),
    )
    return relationships
