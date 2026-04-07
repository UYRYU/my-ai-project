#!/usr/bin/env python3
"""News-tracking trading signal generator.

Polls a configurable list of news sources for Iran/Israel/US war coverage,
classifies every fresh article with Claude, and writes BUY/SELL signals
for crude oil and Nikkei 225 futures into ``signals.json``. The companion
MQL5 Expert Advisor (``IranNewsEA.mq5``) tails that file and places the
actual orders.

Sentiment-to-trade mapping (matches the user's brief):
    escalation     -> crude BUY  / nikkei SELL
    de_escalation  -> crude SELL / nikkei BUY
    neutral        -> both FLAT
"""
from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import anthropic
import feedparser
import httpx
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Configuration (override via environment variables)
# ---------------------------------------------------------------------------

DEFAULT_SOURCES = [
    # The CNN live blog the user pointed at.
    {
        "name": "CNN Iran live",
        "type": "html",
        "url": "https://edition.cnn.com/2026/04/07/world/live-news/iran-war-trump-us-israel",
    },
    # Reuters world news RSS.
    {
        "name": "Reuters World",
        "type": "rss",
        "url": "https://feeds.reuters.com/Reuters/worldNews",
    },
    # BBC world news RSS.
    {
        "name": "BBC World",
        "type": "rss",
        "url": "http://feeds.bbci.co.uk/news/world/rss.xml",
    },
    # Al Jazeera Middle East RSS.
    {
        "name": "Al Jazeera",
        "type": "rss",
        "url": "https://www.aljazeera.com/xml/rss/all.xml",
    },
]

# Pre-filter — only ship articles whose text mentions one of these keywords
# to Claude. Saves cost and avoids spurious classifications.
KEYWORDS = re.compile(
    r"\b(iran|israel|tehran|netanyahu|khamenei|trump|hormuz|strait|"
    r"oil|crude|opec|missile|strike|ceasefire|cease-fire|nuclear|"
    r"idf|irgc|hezbollah|houthi|gaza|lebanon)\b",
    re.IGNORECASE,
)

POLL_INTERVAL_SEC = int(os.getenv("POLL_INTERVAL_SEC", "30"))
SIGNAL_FILE = Path(os.getenv("SIGNAL_FILE", "signals.json"))
SEEN_FILE = Path(os.getenv("SEEN_FILE", ".seen_articles.json"))
MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-4-6")
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "0.6"))
MAX_BODY_CHARS = 6000

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("news_monitor")

# ---------------------------------------------------------------------------
# Verdict model returned by Claude (validated via messages.parse)
# ---------------------------------------------------------------------------

Stance = Literal["escalation", "de_escalation", "neutral"]
Direction = Literal["BUY", "SELL", "FLAT"]


class NewsAnalysis(BaseModel):
    """Structured verdict for one news item."""

    stance: Stance = Field(
        description=(
            "escalation = war intensifying or likely to continue; "
            "de_escalation = ceasefire / withdrawal / diplomatic breakthrough; "
            "neutral = unrelated, ambiguous, or already-priced rumour."
        )
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="How confident the verdict is, 0-1.",
    )
    crude_signal: Direction = Field(
        description="BUY crude on escalation, SELL on de-escalation, FLAT otherwise.",
    )
    nikkei_signal: Direction = Field(
        description="SELL Nikkei on escalation, BUY on de-escalation, FLAT otherwise.",
    )
    headline_summary: str = Field(description="One-line summary of the news.")
    key_phrase: str = Field(description="The most decisive phrase from the article.")


# ---------------------------------------------------------------------------
# Source scraping
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def strip_html(raw: str) -> str:
    text = _TAG_RE.sub(" ", raw)
    text = html.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def fetch_html(url: str) -> str:
    with httpx.Client(
        timeout=15.0,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        r = client.get(url)
        r.raise_for_status()
        return r.text


def collect_articles() -> list[dict]:
    """Return a list of {source, url, title, body, hash} dicts."""
    items: list[dict] = []
    for src in DEFAULT_SOURCES:
        try:
            if src["type"] == "rss":
                items.extend(_collect_rss(src))
            else:
                items.extend(_collect_html(src))
        except Exception as exc:  # noqa: BLE001
            log.warning("source %s failed: %s", src["name"], exc)
    return items


def _collect_rss(src: dict) -> list[dict]:
    feed = feedparser.parse(src["url"])
    out = []
    for entry in feed.entries[:25]:
        title = entry.get("title", "")
        summary = strip_html(entry.get("summary", ""))
        if not (KEYWORDS.search(title) or KEYWORDS.search(summary)):
            continue
        body = f"{title}\n\n{summary}"
        out.append(_make_item(src["name"], entry.get("link", ""), title, body))
    return out


def _collect_html(src: dict) -> list[dict]:
    raw = fetch_html(src["url"])
    text = strip_html(raw)
    if not KEYWORDS.search(text):
        return []
    title = _extract_title(raw) or src["name"]
    body = text[:MAX_BODY_CHARS]
    return [_make_item(src["name"], src["url"], title, body)]


def _extract_title(raw: str) -> str | None:
    m = _TITLE_RE.search(raw)
    return strip_html(m.group(1)) if m else None


def _make_item(source: str, url: str, title: str, body: str) -> dict:
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
    return {
        "source": source,
        "url": url,
        "title": title,
        "body": body,
        "hash": digest,
    }


# ---------------------------------------------------------------------------
# Seen-article cache (so we don't re-analyze the same body twice)
# ---------------------------------------------------------------------------

def load_seen() -> set[str]:
    if not SEEN_FILE.exists():
        return set()
    try:
        return set(json.loads(SEEN_FILE.read_text()))
    except Exception:  # noqa: BLE001
        return set()


def save_seen(seen: set[str]) -> None:
    SEEN_FILE.write_text(json.dumps(list(seen)[-2000:]))


# ---------------------------------------------------------------------------
# Claude classification
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a geopolitical risk analyst on a futures
trading desk. Your job is to read individual news items about the
Iran / Israel / United States conflict and classify the implication
for two markets:

  * Crude oil futures   -> BUY on escalation, SELL on de-escalation
  * Nikkei 225 futures  -> SELL on escalation, BUY on de-escalation

Definitions
-----------
escalation     The war is intensifying, expanding, or clearly likely
               to continue. Examples: new strikes, casualties, troop
               build-ups, blockade of Hormuz, breakdown of talks,
               nuclear escalation rhetoric, oil infrastructure hit.

de_escalation  The conflict is winding down or a peace path is
               opening. Examples: ceasefire agreed, withdrawal of
               troops, sanctions easing, successful diplomacy,
               hostage release, oil flows resuming.

neutral        Off-topic, ambiguous, already-priced, or routine
               commentary that does not move risk.

Be conservative. If the article does not clearly move the needle,
return stance=neutral and FLAT signals. Only emit BUY/SELL when the
news represents a meaningful shift. Confidence below 0.6 will be
ignored downstream.
"""


def build_client() -> anthropic.Anthropic:
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY environment variable is not set")
    return anthropic.Anthropic()


def analyse(client: anthropic.Anthropic, item: dict) -> NewsAnalysis | None:
    user_block = (
        f"SOURCE: {item['source']}\n"
        f"URL: {item['url']}\n"
        f"TITLE: {item['title']}\n\n"
        f"BODY:\n{item['body']}"
    )
    try:
        response = client.messages.parse(
            model=MODEL,
            max_tokens=1024,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_block}],
            output_format=NewsAnalysis,
        )
    except anthropic.APIError as exc:
        log.error("Claude request failed: %s", exc)
        return None
    return response.parsed_output


# ---------------------------------------------------------------------------
# Signal output
# ---------------------------------------------------------------------------

def write_signal(item: dict, verdict: NewsAnalysis) -> None:
    payload = {
        "signal_id": item["hash"],
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "stance": verdict.stance,
        "confidence": verdict.confidence,
        "crude_signal": verdict.crude_signal,
        "nikkei_signal": verdict.nikkei_signal,
        "headline_summary": verdict.headline_summary,
        "key_phrase": verdict.key_phrase,
        "source": item["source"],
        "url": item["url"],
        "title": item["title"],
    }
    tmp = SIGNAL_FILE.with_suffix(SIGNAL_FILE.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    tmp.replace(SIGNAL_FILE)
    log.info(
        "signal %s :: stance=%s conf=%.2f crude=%s nikkei=%s :: %s",
        item["hash"],
        verdict.stance,
        verdict.confidence,
        verdict.crude_signal,
        verdict.nikkei_signal,
        verdict.headline_summary,
    )


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_once(client: anthropic.Anthropic, seen: set[str]) -> None:
    articles = collect_articles()
    new = [a for a in articles if a["hash"] not in seen]
    log.info("collected %d articles, %d new", len(articles), len(new))
    for item in new:
        verdict = analyse(client, item)
        seen.add(item["hash"])
        if verdict is None:
            continue
        if verdict.stance == "neutral" or verdict.confidence < MIN_CONFIDENCE:
            log.info(
                "skipped (stance=%s conf=%.2f): %s",
                verdict.stance,
                verdict.confidence,
                item["title"],
            )
            continue
        write_signal(item, verdict)
    save_seen(seen)


def main() -> int:
    client = build_client()
    seen = load_seen()
    log.info(
        "news_monitor starting; poll=%ds model=%s sources=%d signal_file=%s",
        POLL_INTERVAL_SEC,
        MODEL,
        len(DEFAULT_SOURCES),
        SIGNAL_FILE,
    )
    while True:
        try:
            run_once(client, seen)
        except KeyboardInterrupt:
            log.info("stopping on Ctrl-C")
            return 0
        except Exception as exc:  # noqa: BLE001
            log.exception("loop error: %s", exc)
        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    sys.exit(main())
