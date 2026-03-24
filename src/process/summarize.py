"""Summarise a RawArticle into a structured Japanese Summary.

Behaviour:
- If ``ANTHROPIC_API_KEY`` is set, calls the Claude API using the prompt in
  ``prompts/summarize_prompt.md``.
- Otherwise falls back to a template-based dummy summary so the full pipeline
  can be tested without API access.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from models import RawArticle, Summary
from utils.fileio import read_text
from utils.logger import setup_logger

logger = setup_logger(__name__)

_PROMPT_PATH = Path("prompts/summarize_prompt.md")


# ---------------------------------------------------------------------------
# Dummy fallback
# ---------------------------------------------------------------------------

def _dummy_summary(article: RawArticle) -> Summary:
    """Generate a template-based Japanese summary without API access."""
    snippet = article.body[:120].replace("\n", " ")
    return Summary(
        article_id=article.id,
        title=f"【要約】{article.title}",
        source=article.source_name,
        url=article.url,
        summary_ja=(
            f"「{article.title}」についての記事です。"
            f"{snippet}…（ダミー要約 – ANTHROPIC_API_KEY を設定すると本物の要約が生成されます）"
        ),
        key_points=[
            "AIの新たな能力向上が報告されている",
            "実装コストや推論速度の改善が示唆されている",
            "業界・研究コミュニティへの影響が予想される",
        ],
        actionable_takeaways=[
            "公式ブログ・論文で詳細を確認する",
            "自社プロダクトへの応用可能性を検討する",
        ],
        quoted_claims_to_verify=[
            "ベンチマーク数値は独立した再現実験で確認が必要",
        ],
    )


# ---------------------------------------------------------------------------
# API-based summarisation
# ---------------------------------------------------------------------------

def _call_claude(prompt: str, settings: dict) -> str:
    """Call the Claude API and return the raw response text."""
    from anthropic import Anthropic  # noqa: PLC0415

    api_key = os.getenv("ANTHROPIC_API_KEY")
    client = Anthropic(api_key=api_key)
    model = settings.get("ai", {}).get("model", "claude-opus-4-6")
    max_tokens = settings.get("ai", {}).get("max_tokens", 2048)

    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def _extract_json(text: str) -> dict:
    """Extract the first JSON object from *text*, tolerating markdown fences."""
    # Strip ```json ... ``` fences
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```", "", text)
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError("No JSON object found in response.")
    return json.loads(text[start:end])


def _api_summary(article: RawArticle, settings: dict) -> Summary:
    """Summarise *article* using the Claude API."""
    template = read_text(_PROMPT_PATH)
    prompt = template.format(
        title=article.title,
        source=article.source_name,
        url=article.url,
        body=article.body[:4000],  # Stay within reasonable token budget
    )
    raw_response = _call_claude(prompt, settings)
    data = _extract_json(raw_response)

    return Summary(
        article_id=article.id,
        title=data.get("title", article.title),
        source=data.get("source", article.source_name),
        url=data.get("url", article.url),
        summary_ja=data.get("summary_ja", ""),
        key_points=data.get("key_points", []),
        actionable_takeaways=data.get("actionable_takeaways", []),
        quoted_claims_to_verify=data.get("quoted_claims_to_verify", []),
    )


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def summarize_article(article: RawArticle, settings: dict) -> Summary:
    """Summarise *article* in Japanese.

    Uses the Claude API when ``ANTHROPIC_API_KEY`` is set; otherwise returns a
    template-based dummy summary.

    Args:
        article: Parsed :class:`~models.RawArticle`.
        settings: Loaded ``config/settings.yaml`` dict.

    Returns:
        A populated :class:`~models.Summary`.
    """
    if not os.getenv("ANTHROPIC_API_KEY"):
        logger.warning("ANTHROPIC_API_KEY not set – using dummy summary for '%s'", article.title)
        return _dummy_summary(article)

    try:
        summary = _api_summary(article, settings)
        logger.info("Summarised '%s' via Claude API", article.title)
        return summary
    except Exception as exc:
        logger.error("API summarisation failed for '%s': %s – using dummy.", article.title, exc)
        return _dummy_summary(article)
