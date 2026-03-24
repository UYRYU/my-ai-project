"""Re-structure a Summary into a Japanese-audience-oriented StructuredContent.

The restructuring separates content into three lenses:
  - 思想 (Thought)        → 背景・文脈・哲学的含意
  - 実装 (Implementation) → 技術的詳細・実践方法
  - 示唆 (Implications)   → 業界・社会・個人への影響

Behaviour:
- If ``ANTHROPIC_API_KEY`` is set, calls the Claude API.
- Otherwise returns a template-based dummy structure.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from models import Summary, StructuredContent
from utils.fileio import read_text
from utils.logger import setup_logger

logger = setup_logger(__name__)

_PROMPT_PATH = Path("prompts/structure_prompt.md")


# ---------------------------------------------------------------------------
# Dummy fallback
# ---------------------------------------------------------------------------

def _dummy_structure(summary: Summary) -> StructuredContent:
    return StructuredContent(
        article_id=summary.article_id,
        angle="技術革新がもたらす実務インパクト",
        audience="AIに関心のあるエンジニア・プロダクトマネージャー",
        core_insight=(
            f"{summary.source}が発表したこの技術は、"
            "従来の課題を新しいアプローチで解決しようとしている。"
            "（ダミー構造化 – ANTHROPIC_API_KEY を設定すると本物の分析が生成されます）"
        ),
        implementation_hint="まず公式ドキュメントとAPIリファレンスを確認し、小規模なPoCから始める。",
        note_outline=[
            "## 導入：なぜ今これが重要か",
            "## 要点整理：3つのポイント",
            "## 背景と文脈",
            "## 実装への示唆",
            "## まとめと今後の展望",
        ],
        x_hooks=[
            f"{summary.source}の新発表、見逃せない3つのポイント→",
            f"AIが変わる。{summary.source}の最新動向を読み解く",
            "エンジニア必読。この変化を先読みした人が有利になる理由",
        ],
    )


# ---------------------------------------------------------------------------
# API-based structuring
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict:
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```", "", text)
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError("No JSON object found in response.")
    return json.loads(text[start:end])


def _api_structure(summary: Summary, settings: dict) -> StructuredContent:
    from anthropic import Anthropic  # noqa: PLC0415

    template = read_text(_PROMPT_PATH)
    prompt = template.format(
        title=summary.title,
        source=summary.source,
        url=summary.url,
        summary_ja=summary.summary_ja,
        key_points="\n".join(f"- {p}" for p in summary.key_points),
        actionable_takeaways="\n".join(f"- {p}" for p in summary.actionable_takeaways),
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
    data = _extract_json(message.content[0].text)

    return StructuredContent(
        article_id=summary.article_id,
        angle=data.get("angle", ""),
        audience=data.get("audience", ""),
        core_insight=data.get("core_insight", ""),
        implementation_hint=data.get("implementation_hint", ""),
        note_outline=data.get("note_outline", []),
        x_hooks=data.get("x_hooks", []),
    )


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def structure_content(summary: Summary, settings: dict) -> StructuredContent:
    """Convert a *summary* into a :class:`~models.StructuredContent` for Japanese readers.

    Args:
        summary: The :class:`~models.Summary` to structure.
        settings: Loaded ``config/settings.yaml`` dict.

    Returns:
        A populated :class:`~models.StructuredContent`.
    """
    if not os.getenv("ANTHROPIC_API_KEY"):
        logger.warning("ANTHROPIC_API_KEY not set – using dummy structure for '%s'", summary.title)
        return _dummy_structure(summary)

    try:
        structured = _api_structure(summary, settings)
        logger.info("Structured content for '%s' via Claude API", summary.title)
        return structured
    except Exception as exc:
        logger.error("API structuring failed for '%s': %s – using dummy.", summary.title, exc)
        return _dummy_structure(summary)
