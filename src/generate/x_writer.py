"""Generate X (Twitter) post drafts from a Summary + StructuredContent.

Each article produces ``count_per_source`` (default 3) post drafts.
Each draft varies in tone:
  - 案1: 問いかけ型（読者に問いかけるフック）
  - 案2: 箇条書き型（要点を端的に列挙）
  - 案3: 一言洞察型（鋭い一言＋補足）

Behaviour:
- If ``ANTHROPIC_API_KEY`` is set, calls the Claude API.
- Otherwise returns template-based drafts.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from models import Summary, StructuredContent, XPost
from utils.fileio import read_text
from utils.logger import setup_logger

logger = setup_logger(__name__)

_PROMPT_PATH = Path("prompts/x_post_prompt.md")


# ---------------------------------------------------------------------------
# Dummy fallback
# ---------------------------------------------------------------------------

def _dummy_x_posts(summary: Summary, structured: StructuredContent, count: int) -> list[XPost]:
    """Generate template X posts without API access."""
    templates = [
        XPost(
            hook=f"「{summary.title}」が話題に。",
            body=(
                f"ポイントは3つ：\n"
                f"① {summary.key_points[0] if summary.key_points else 'AIの能力向上'}\n"
                f"② {summary.key_points[1] if len(summary.key_points) > 1 else '実装コストの低減'}\n"
                f"③ {summary.key_points[2] if len(summary.key_points) > 2 else '業界への波及効果'}"
            ),
            closing="見逃せない動向です。",
            source_reference=f"▶ {summary.url}",
        ),
        XPost(
            hook=f"{summary.source}の新展開、あなたの仕事はどう変わる？",
            body=summary.summary_ja[:100] + "…" if len(summary.summary_ja) > 100 else summary.summary_ja,
            closing=(
                f"示唆：{summary.actionable_takeaways[0]}"
                if summary.actionable_takeaways
                else "まず小さく試してみることが大事。"
            ),
            source_reference=f"詳細→ {summary.url}",
        ),
        XPost(
            hook=structured.core_insight[:60] + "…" if len(structured.core_insight) > 60 else structured.core_insight,
            body=f"背景：{structured.angle}\n対象：{structured.audience}",
            closing=structured.implementation_hint[:80] if structured.implementation_hint else "まずPoCから。",
            source_reference=f"出典: {summary.source} {summary.url}",
        ),
    ]
    posts = templates[:count]
    logger.info("Generated %d dummy X posts for '%s'", len(posts), summary.title)
    return posts


# ---------------------------------------------------------------------------
# API-based generation
# ---------------------------------------------------------------------------

def _extract_json_array(text: str) -> list:
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```", "", text)
    start = text.find("[")
    end = text.rfind("]") + 1
    if start == -1 or end == 0:
        raise ValueError("No JSON array found in response.")
    return json.loads(text[start:end])


def _api_x_posts(
    summary: Summary,
    structured: StructuredContent,
    settings: dict,
    count: int,
) -> list[XPost]:
    from anthropic import Anthropic  # noqa: PLC0415

    template = read_text(_PROMPT_PATH)
    prompt = template.format(
        title=summary.title,
        source=summary.source,
        url=summary.url,
        summary_ja=summary.summary_ja,
        key_points="\n".join(f"- {p}" for p in summary.key_points),
        actionable_takeaways="\n".join(f"- {p}" for p in summary.actionable_takeaways),
        core_insight=structured.core_insight,
        implementation_hint=structured.implementation_hint,
        x_hooks="\n".join(f"- {h}" for h in structured.x_hooks),
        count=count,
    )

    api_key = os.getenv("ANTHROPIC_API_KEY")
    client = Anthropic(api_key=api_key)
    model = settings.get("ai", {}).get("model", "claude-opus-4-6")
    max_tokens = settings.get("ai", {}).get("max_tokens", 2048)

    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    items = _extract_json_array(message.content[0].text)

    posts: list[XPost] = []
    for item in items[:count]:
        posts.append(
            XPost(
                hook=item.get("hook", ""),
                body=item.get("body", ""),
                closing=item.get("closing", ""),
                source_reference=item.get("source_reference", summary.url),
            )
        )
    return posts


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def generate_x_posts(
    summary: Summary,
    structured: StructuredContent,
    settings: dict,
) -> list[XPost]:
    """Generate X post drafts for a given *summary* and *structured* content.

    Args:
        summary: The :class:`~models.Summary` for this article.
        structured: The :class:`~models.StructuredContent` for this article.
        settings: Loaded ``config/settings.yaml`` dict.

    Returns:
        List of :class:`~models.XPost` drafts (length = ``x_posts.count_per_source``).
    """
    count: int = settings.get("x_posts", {}).get("count_per_source", 3)

    if not os.getenv("ANTHROPIC_API_KEY"):
        logger.warning("ANTHROPIC_API_KEY not set – using dummy X posts for '%s'", summary.title)
        return _dummy_x_posts(summary, structured, count)

    try:
        posts = _api_x_posts(summary, structured, settings, count)
        logger.info("Generated %d X posts via Claude API for '%s'", len(posts), summary.title)
        return posts
    except Exception as exc:
        logger.error("API X post generation failed for '%s': %s – using dummy.", summary.title, exc)
        return _dummy_x_posts(summary, structured, count)
