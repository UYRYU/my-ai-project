"""Domain-agnostic similarity engine.

Wraps the embedding + cosine-similarity logic so any adapter can:
  1. Classify instruments into categories
  2. Find related instrument pairs
  3. Filter by temporal proximity
"""

from __future__ import annotations

import logging
from datetime import timedelta

import numpy as np

from .primitives import Instrument

logger = logging.getLogger(__name__)

# Re-use the embedding backend from nlp module
from polymarket_arbitrage.nlp.embeddings import (
    cosine_similarity_matrix,
    encode_texts,
)


def classify_by_category(
    instruments: list[Instrument],
    categories: list[str],
) -> dict[str, list[Instrument]]:
    """Classify instruments into categories via embedding similarity."""
    if not instruments:
        return {c: [] for c in categories}

    texts = [inst.name for inst in instruments]
    all_texts = categories + texts
    all_emb = encode_texts(all_texts)
    cat_emb = all_emb[: len(categories)]
    inst_emb = all_emb[len(categories) :]

    sim = cosine_similarity_matrix(inst_emb, cat_emb)
    best = np.argmax(sim, axis=1)

    result: dict[str, list[Instrument]] = {c: [] for c in categories}
    for i, inst in enumerate(instruments):
        cat = categories[best[i]]
        result[cat].append(inst)
    return result


def find_similar_pairs(
    instruments: list[Instrument],
    threshold: float = 0.5,
) -> list[tuple[Instrument, Instrument, float]]:
    """Find pairs of semantically similar instruments."""
    if len(instruments) < 2:
        return []

    texts = [inst.name for inst in instruments]
    emb = encode_texts(texts)
    sim = cosine_similarity_matrix(emb, emb)

    pairs: list[tuple[Instrument, Instrument, float]] = []
    for i in range(len(instruments)):
        for j in range(i + 1, len(instruments)):
            score = float(sim[i, j])
            if score >= threshold:
                pairs.append((instruments[i], instruments[j], score))
    pairs.sort(key=lambda x: -x[2])
    return pairs


def filter_temporal(
    instruments: list[Instrument],
    max_days: int = 30,
) -> list[tuple[Instrument, Instrument]]:
    """Return pairs of instruments within temporal proximity."""
    delta = timedelta(days=max_days)
    pairs = []
    for i, a in enumerate(instruments):
        if a.end_date is None:
            continue
        for j in range(i + 1, len(instruments)):
            b = instruments[j]
            if b.end_date is None:
                continue
            if abs(a.end_date - b.end_date) <= delta:
                pairs.append((a, b))
    return pairs
