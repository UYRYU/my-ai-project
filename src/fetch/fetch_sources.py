"""Fetch new content from monitoring sources defined in sources.yaml.

Design:
- ``load_sources()`` reads sources.yaml and returns a list of Source objects.
- ``fetch_source()`` dispatches to the appropriate fetcher based on platform.
- Each fetcher returns a list of raw dicts ready for parse_article.py.
- A ``DummyFetcher`` provides realistic sample data so the pipeline runs
  end-to-end without real network access.

Adding a new platform:
  1. Create a new function ``fetch_<platform>(source: Source) -> list[dict]``.
  2. Register it in the ``_FETCHERS`` mapping inside ``fetch_source()``.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from models import Source
from utils.fileio import read_yaml
from utils.logger import setup_logger

logger = setup_logger(__name__)


# ---------------------------------------------------------------------------
# Source loading
# ---------------------------------------------------------------------------

def load_sources(path: str = "sources.yaml") -> list[Source]:
    """Load monitoring sources from *path* (relative to cwd)."""
    data = read_yaml(path)
    sources: list[Source] = []
    for entry in data.get("sources", []):
        try:
            sources.append(
                Source(
                    name=entry["name"],
                    platform=entry["platform"],
                    handle_or_url=entry["handle_or_url"],
                    enabled=entry.get("enabled", True),
                    priority=entry.get("priority", 99),
                )
            )
        except KeyError as exc:
            logger.warning("Skipping malformed source entry (missing key %s): %s", exc, entry)
    sources.sort(key=lambda s: s.priority)
    logger.info("Loaded %d sources from %s", len(sources), path)
    return sources


# ---------------------------------------------------------------------------
# Dummy fetcher (used when API keys / real fetchers are unavailable)
# ---------------------------------------------------------------------------

_DUMMY_ARTICLES: list[dict[str, str]] = [
    {
        "title": "GPT-5 Achieves Human-Level Performance on Complex Reasoning Benchmarks",
        "body": (
            "OpenAI has announced that GPT-5 has achieved human-level performance on several "
            "complex reasoning benchmarks including MATH, HumanEval, and MMLU. The model "
            "demonstrates improved chain-of-thought reasoning, reduced hallucination rates by "
            "40%, and supports a 128k context window natively. Key architectural improvements "
            "include a new mixture-of-experts design that reduces inference cost while "
            "increasing capability. The model is available via API starting today, with "
            "consumer-facing products to follow. Researchers note that GPT-5 shows emergent "
            "abilities in multi-step planning and code generation that were not present in "
            "earlier versions. The model also supports real-time tool use and function calling "
            "with significantly lower latency."
        ),
        "url": "https://openai.com/blog/gpt-5-announcement",
        "date": "2026-03-20T09:00:00Z",
    },
    {
        "title": "Anthropic Releases Claude 3.7 with Enhanced Multimodal Capabilities",
        "body": (
            "Anthropic today released Claude 3.7, featuring significantly enhanced multimodal "
            "understanding including video comprehension, improved code generation with built-in "
            "execution, and a new 'extended thinking' mode for complex problem-solving. The "
            "model shows a 30% improvement on coding benchmarks and introduces a new safety "
            "mechanism called Constitutional AI v2, which reduces harmful outputs while "
            "preserving helpfulness. Claude 3.7 Opus is available via API and through the "
            "Claude.ai platform. Notable is the model's ability to reason over long documents "
            "with a 200k context window. Enterprise customers report significant productivity "
            "gains in software development workflows."
        ),
        "url": "https://www.anthropic.com/news/claude-3-7",
        "date": "2026-03-21T10:00:00Z",
    },
    {
        "title": "Google DeepMind Gemini Ultra 2.0 Sets New State-of-the-Art on Science Benchmarks",
        "body": (
            "Google DeepMind's Gemini Ultra 2.0 has set new state-of-the-art results on "
            "scientific reasoning benchmarks including GPQA Diamond (92.3%) and FrontierMath. "
            "The model demonstrates expert-level performance in physics, chemistry, and biology. "
            "Key features include native integration with Google's scientific databases, "
            "real-time literature search, and the ability to run computational experiments "
            "through code execution. The model is now available through Google Cloud Vertex AI "
            "and the Gemini API. DeepMind researchers highlight that the model can assist in "
            "drug discovery workflows, reducing initial screening time by up to 60%."
        ),
        "url": "https://deepmind.google/discover/blog/gemini-ultra-2",
        "date": "2026-03-22T08:00:00Z",
    },
]


def _make_article_id(url: str, source_name: str) -> str:
    """Generate a stable ID from URL + source name."""
    raw = f"{source_name}:{url}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def fetch_dummy(source: Source) -> list[dict[str, Any]]:
    """Return hard-coded sample articles attributed to *source*."""
    logger.info("[DUMMY] Fetching articles for source: %s", source.name)
    results = []
    for article in _DUMMY_ARTICLES:
        results.append(
            {
                **article,
                "source_name": source.name,
                "platform": source.platform,
                "id": _make_article_id(article["url"], source.name),
            }
        )
    # Return only first article per source to avoid flooding the queue
    return results[:1]


# ---------------------------------------------------------------------------
# Platform-specific fetchers (stubs – replace with real implementations)
# ---------------------------------------------------------------------------

def fetch_web(source: Source) -> list[dict[str, Any]]:
    """Fetch articles from a web/blog source.

    Current implementation: returns dummy data.
    Future: scrape RSS feed or HTML page.
    """
    logger.info("[WEB] Fetching from %s (%s)", source.name, source.handle_or_url)
    return fetch_dummy(source)


def fetch_rss(source: Source) -> list[dict[str, Any]]:
    """Fetch articles via RSS feed.

    Current implementation: returns dummy data.
    Future: use ``feedparser`` to retrieve and parse the RSS/Atom feed.
    """
    logger.info("[RSS] Fetching from %s (%s)", source.name, source.handle_or_url)
    return fetch_dummy(source)


def fetch_x(source: Source) -> list[dict[str, Any]]:
    """Fetch posts from X (Twitter).

    Current implementation: returns dummy data.
    Future: use X API v2 to fetch recent tweets from the handle.
    """
    logger.info("[X] Fetching from %s (%s)", source.name, source.handle_or_url)
    return fetch_dummy(source)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_FETCHERS = {
    "web": fetch_web,
    "rss": fetch_rss,
    "x": fetch_x,
}


def fetch_source(source: Source) -> list[dict[str, Any]]:
    """Fetch articles/posts for a single *source*.

    Dispatches to the appropriate platform fetcher.  Falls back to the dummy
    fetcher if no matching platform handler is registered.

    Args:
        source: A :class:`~models.Source` instance.

    Returns:
        List of raw article dicts.
    """
    fetcher = _FETCHERS.get(source.platform, fetch_dummy)
    try:
        return fetcher(source)
    except Exception as exc:
        logger.error("Failed to fetch source '%s': %s", source.name, exc)
        return []
