"""Parse and normalise raw article dicts into RawArticle dataclass instances.

Input is the raw dict produced by ``fetch_sources.fetch_source()``.
Output is a standardised :class:`~models.RawArticle`.

Adding HTML / RSS extraction:
  - Implement ``extract_from_url(url)`` using ``requests`` + ``BeautifulSoup``.
  - Call it inside ``parse_article()`` when ``body`` is short or missing.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from models import RawArticle
from utils.logger import setup_logger

logger = setup_logger(__name__)

# Minimum body length to consider the content usable without re-fetching
_MIN_BODY_LENGTH = 50


# ---------------------------------------------------------------------------
# Text cleaning helpers
# ---------------------------------------------------------------------------

def _clean_text(text: str) -> str:
    """Strip excessive whitespace and normalise line endings."""
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def _extract_title(raw: dict[str, Any]) -> str:
    title = raw.get("title", "").strip()
    if not title:
        # Fall back to first line of body
        body = raw.get("body", "")
        title = body.split("\n")[0][:80] if body else "Untitled"
    return title


def _extract_date(raw: dict[str, Any]) -> str:
    date = raw.get("date", "")
    if date:
        return date
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_id(url: str, source_name: str) -> str:
    raw = f"{source_name}:{url}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Optional: lightweight URL body extraction
# ---------------------------------------------------------------------------

def _try_fetch_body_from_url(url: str) -> str:
    """Attempt to extract article body from *url* using requests + BS4.

    Returns an empty string on any failure so the caller can fall back
    gracefully.
    """
    try:
        import requests  # noqa: PLC0415
        from bs4 import BeautifulSoup  # noqa: PLC0415

        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove noise elements
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        # Prefer <article> or <main> tags; fall back to <body>
        container = soup.find("article") or soup.find("main") or soup.body
        if container:
            paragraphs = container.find_all("p")
            return "\n\n".join(p.get_text() for p in paragraphs if p.get_text().strip())
    except Exception as exc:
        logger.debug("Could not fetch body from URL %s: %s", url, exc)
    return ""


# ---------------------------------------------------------------------------
# Main parse function
# ---------------------------------------------------------------------------

def parse_article(raw: dict[str, Any]) -> RawArticle:
    """Convert a raw fetched dict into a normalised :class:`~models.RawArticle`.

    Args:
        raw: Dict with keys: ``title``, ``body``, ``url``, ``date``,
             ``source_name``, ``platform``.  All optional except ``url``.

    Returns:
        A :class:`~models.RawArticle` with all fields populated.
    """
    url = raw.get("url", "").strip()
    source_name = raw.get("source_name", "Unknown")
    platform = raw.get("platform", "web")

    title = _extract_title(raw)
    body = _clean_text(raw.get("body", ""))
    date = _extract_date(raw)
    article_id = raw.get("id") or _make_id(url, source_name)

    # If body is too short and we have a URL, attempt live extraction
    if len(body) < _MIN_BODY_LENGTH and url.startswith("http"):
        logger.info("Body too short for '%s', attempting URL extraction…", title)
        fetched = _try_fetch_body_from_url(url)
        if fetched:
            body = _clean_text(fetched)
            logger.info("Extracted %d chars from URL.", len(body))

    if not body:
        body = f"[本文を取得できませんでした。元記事をご確認ください: {url}]"
        logger.warning("Empty body for article '%s' (%s)", title, url)

    article = RawArticle(
        id=article_id,
        title=title,
        body=body,
        url=url,
        date=date,
        source_name=source_name,
        platform=platform,
    )
    logger.info("Parsed article: '%s' (%d chars)", article.title, len(article.body))
    return article
