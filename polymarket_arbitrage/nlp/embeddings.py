"""Text embedding and topic classification.

The paper uses Linq-Embed-Mistral for generating embeddings to:
1. Classify markets into topics (Politics, Economy, Tech, Crypto, etc.)
2. Find semantically similar markets for combinatorial arbitrage candidates.

We use sentence-transformers with a configurable model (default: all-MiniLM-L6-v2
for lightweight local use; users can switch to a larger model).
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional

import numpy as np

from polymarket_arbitrage.config import (
    MAX_TEMPORAL_DISTANCE_DAYS,
    SIMILARITY_THRESHOLD,
    TOPICS,
)
from polymarket_arbitrage.models.market import Market

logger = logging.getLogger(__name__)

# Lazy-loaded model to avoid import cost when not needed
_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        from polymarket_arbitrage.config import DEFAULT_EMBEDDING_MODEL
        logger.info("Loading embedding model: %s", DEFAULT_EMBEDDING_MODEL)
        _model = SentenceTransformer(DEFAULT_EMBEDDING_MODEL)
    return _model


def encode_texts(texts: list[str]) -> np.ndarray:
    """Encode a list of texts into embedding vectors."""
    model = _get_model()
    return model.encode(texts, normalize_embeddings=True, show_progress_bar=False)


def cosine_similarity_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Compute pairwise cosine similarity between two sets of embeddings.

    When embeddings are L2-normalized, cosine similarity is just the dot product.
    """
    return a @ b.T


# ------------------------------------------------------------------
# Topic classification (Step 2 of the paper's pipeline)
# ------------------------------------------------------------------

def classify_topics(
    markets: list[Market],
    topics: Optional[list[str]] = None,
) -> dict[str, list[Market]]:
    """Classify markets into topics using embedding cosine similarity.

    For each market question, compute cosine similarity against each topic
    label embedding and assign to the most similar topic.

    Returns a dict mapping topic -> list of markets.
    """
    if topics is None:
        topics = TOPICS

    if not markets:
        return {t: [] for t in topics}

    questions = [m.question for m in markets]

    topic_embeddings = encode_texts(topics)
    question_embeddings = encode_texts(questions)

    # similarity: (n_questions, n_topics)
    sim = cosine_similarity_matrix(question_embeddings, topic_embeddings)
    best_topics = np.argmax(sim, axis=1)

    result: dict[str, list[Market]] = {t: [] for t in topics}
    for i, market in enumerate(markets):
        topic = topics[best_topics[i]]
        result[topic].append(market)

    for topic, mlist in result.items():
        logger.info("Topic '%s': %d markets", topic, len(mlist))

    return result


# ------------------------------------------------------------------
# Temporal filtering (Step 1 of the paper's pipeline)
# ------------------------------------------------------------------

def filter_temporal_proximity(
    markets: list[Market],
    max_days: int = MAX_TEMPORAL_DISTANCE_DAYS,
) -> list[tuple[Market, Market]]:
    """Find pairs of markets within temporal proximity.

    Markets are considered temporally related if their end dates
    are within max_days of each other.
    """
    pairs: list[tuple[Market, Market]] = []
    delta = timedelta(days=max_days)

    for i, a in enumerate(markets):
        if a.end_date is None:
            continue
        for j in range(i + 1, len(markets)):
            b = markets[j]
            if b.end_date is None:
                continue
            if abs(a.end_date - b.end_date) <= delta:
                pairs.append((a, b))

    return pairs


# ------------------------------------------------------------------
# Semantic similarity for related market discovery
# ------------------------------------------------------------------

def find_related_markets(
    markets: list[Market],
    threshold: float = SIMILARITY_THRESHOLD,
) -> list[tuple[Market, Market, float]]:
    """Find pairs of semantically similar markets.

    Uses embedding cosine similarity to identify markets whose questions
    are topically related, which are candidates for combinatorial arbitrage.

    Returns list of (market_a, market_b, similarity_score) tuples.
    """
    if len(markets) < 2:
        return []

    questions = [m.question for m in markets]
    embeddings = encode_texts(questions)
    sim = cosine_similarity_matrix(embeddings, embeddings)

    related: list[tuple[Market, Market, float]] = []
    for i in range(len(markets)):
        for j in range(i + 1, len(markets)):
            score = float(sim[i, j])
            if score >= threshold:
                related.append((markets[i], markets[j], score))

    related.sort(key=lambda x: x[2], reverse=True)
    logger.info(
        "Found %d related market pairs (threshold=%.2f) from %d markets",
        len(related), threshold, len(markets),
    )
    return related
