"""Post approved X drafts to X (Twitter) via the API.

Uses OAuth 1.0a (API Key + Access Token) so the tweet is posted as the
authenticated user (@Agent_EnginJP).

Credentials are read from environment variables:
  X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET

Posted item IDs are persisted in ``data/state/posted_x.json`` so that
re-running this module never double-posts the same draft.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import tweepy

from models import ApprovalItem
from review.approval_queue import ApprovalQueue
from utils.logger import setup_logger

logger = setup_logger(__name__)

_STATE_FILE = Path("data/state/posted_x.json")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_post_text(item: ApprovalItem) -> str:
    c = item.content
    parts = [c.get(k, "").strip() for k in ("hook", "body", "closing", "source_reference")]
    return "\n\n".join(p for p in parts if p)


def _load_posted_ids(state_file: Path) -> dict[str, str]:
    """Return {item_id: tweet_id} for already-posted items."""
    if not state_file.exists():
        return {}
    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_posted_ids(state_file: Path, data: dict[str, str]) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_client() -> tweepy.Client:
    api_key = os.environ.get("X_API_KEY", "")
    api_secret = os.environ.get("X_API_SECRET", "")
    access_token = os.environ.get("X_ACCESS_TOKEN", "")
    access_token_secret = os.environ.get("X_ACCESS_TOKEN_SECRET", "")

    missing = [k for k, v in {
        "X_API_KEY": api_key,
        "X_API_SECRET": api_secret,
        "X_ACCESS_TOKEN": access_token,
        "X_ACCESS_TOKEN_SECRET": access_token_secret,
    }.items() if not v]

    if missing:
        raise EnvironmentError(
            f"X API credentials not set: {', '.join(missing)}\n"
            "Set them in .env or as environment variables."
        )

    return tweepy.Client(
        consumer_key=api_key,
        consumer_secret=api_secret,
        access_token=access_token,
        access_token_secret=access_token_secret,
    )


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def post_approved_x_posts(
    queue: ApprovalQueue,
    state_file: str | Path = _STATE_FILE,
    dry_run: bool = False,
) -> list[str]:
    """Post all approved X drafts that have not yet been posted.

    Args:
        queue: The :class:`~review.approval_queue.ApprovalQueue` instance.
        state_file: Path to JSON file tracking posted item IDs.
        dry_run: If True, print the post text without actually posting.

    Returns:
        List of tweet IDs (or item IDs in dry-run mode) for newly posted tweets.
    """
    state_path = Path(state_file)
    posted = _load_posted_ids(state_path)

    approved = [
        item for item in queue.get_approved()
        if item.item_type == "x_post" and item.id not in posted
    ]

    if not approved:
        logger.info("No new approved X posts to publish.")
        print("投稿する新規承認済みX投稿はありません。")
        return []

    if not dry_run:
        client = _get_client()

    results: list[str] = []
    for item in approved:
        text = _build_post_text(item)
        char_count = len(text)

        if char_count > 280:
            logger.warning(
                "Post '%s' is %d chars (>280). Truncating to 280.", item.title, char_count
            )
            text = text[:277] + "…"

        if dry_run:
            print(f"\n[DRY RUN] ─── {item.title} ───")
            print(text)
            print(f"({len(text)} 文字)")
            posted[item.id] = f"dry_run_{item.id}"
            results.append(item.id)
            continue

        try:
            response = client.create_tweet(text=text)
            tweet_id = str(response.data["id"])
            posted[item.id] = tweet_id
            _save_posted_ids(state_path, posted)
            logger.info("Posted tweet id=%s for item '%s'", tweet_id, item.title)
            print(f"✓ 投稿完了: {item.title} (tweet_id={tweet_id})")
            results.append(tweet_id)
        except tweepy.TweepyException as exc:
            logger.error("Failed to post '%s': %s", item.title, exc)
            print(f"✗ 投稿失敗: {item.title}\n  エラー: {exc}")

    if not dry_run and results:
        _save_posted_ids(state_path, posted)

    return results
