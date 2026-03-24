"""Deduplication: check whether a Summary is too similar to past processed content.

Processed summaries are stored in ``data/state/processed_summaries.json`` as a
list of text snippets.  Each new summary is compared against all stored texts
using the configured similarity method and threshold.

Workflow:
1. ``check_duplicate(summary, settings)`` – returns ``(is_dup, max_score)``.
2. ``save_processed_summary(summary, settings)`` – adds the summary text to
   the state file so future checks can detect repetition.
"""
from __future__ import annotations

from pathlib import Path

from models import Summary
from utils.fileio import read_json, write_json
from utils.logger import setup_logger
from utils.similarity import compute_similarity

logger = setup_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _summary_text(summary: Summary) -> str:
    """Combine the key textual fields into one string for comparison."""
    parts = [
        summary.title,
        summary.summary_ja,
        " ".join(summary.key_points),
    ]
    return " ".join(p for p in parts if p)


def _state_path(settings: dict) -> Path:
    path = settings.get("similarity", {}).get(
        "state_file", "data/state/processed_summaries.json"
    )
    return Path(path)


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def check_duplicate(summary: Summary, settings: dict) -> tuple[bool, float]:
    """Check whether *summary* is too similar to previously processed content.

    Args:
        summary: The :class:`~models.Summary` to check.
        settings: Loaded ``config/settings.yaml`` dict.

    Returns:
        ``(is_duplicate, max_similarity_score)`` tuple.
        ``is_duplicate`` is ``True`` when the score meets or exceeds the
        configured threshold.
    """
    sim_cfg = settings.get("similarity", {})
    threshold: float = sim_cfg.get("threshold", 0.75)
    method: str = sim_cfg.get("method", "cosine")

    state_path = _state_path(settings)
    past_texts: list[str] = read_json(state_path)  # type: ignore[assignment]
    if not isinstance(past_texts, list):
        past_texts = []

    new_text = _summary_text(summary)
    max_score = 0.0

    for past_text in past_texts:
        score = compute_similarity(new_text, past_text, method=method)
        if score > max_score:
            max_score = score

    is_dup = max_score >= threshold
    if is_dup:
        logger.info(
            "Duplicate detected for '%s' (score=%.2f >= threshold=%.2f)",
            summary.title,
            max_score,
            threshold,
        )
    else:
        logger.debug(
            "No duplicate for '%s' (max_score=%.2f)", summary.title, max_score
        )

    return is_dup, max_score


def save_processed_summary(summary: Summary, settings: dict) -> None:
    """Persist the text of *summary* to the state file for future dedup checks.

    Args:
        summary: The :class:`~models.Summary` to persist.
        settings: Loaded ``config/settings.yaml`` dict.
    """
    state_path = _state_path(settings)
    past_texts: list[str] = read_json(state_path)  # type: ignore[assignment]
    if not isinstance(past_texts, list):
        past_texts = []

    past_texts.append(_summary_text(summary))
    write_json(state_path, past_texts)
    logger.debug("Saved processed summary for '%s'", summary.title)
