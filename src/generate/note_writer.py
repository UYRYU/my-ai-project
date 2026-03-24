"""Generate a note.com article draft in Markdown format.

The draft follows a structure designed for future monetisation:
  - 無料部分: タイトル、導入、要点整理
  - 深掘り部分（有料化候補）: 背景/文脈、実装への示唆
  - まとめ・出典（共通）

Behaviour:
- If ``ANTHROPIC_API_KEY`` is set, calls the Claude API.
- Otherwise returns a template-based Markdown draft.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from models import Summary, StructuredContent, NoteDraft
from utils.fileio import read_text
from utils.logger import setup_logger

logger = setup_logger(__name__)

_PROMPT_PATH = Path("prompts/note_prompt.md")


# ---------------------------------------------------------------------------
# Dummy fallback
# ---------------------------------------------------------------------------

def _dummy_note_draft(summary: Summary, structured: StructuredContent) -> NoteDraft:
    """Generate a template-based Markdown note without API access."""
    key_points_md = "\n".join(f"- {p}" for p in summary.key_points) or "- （要点なし）"
    takeaways_md = "\n".join(f"- {p}" for p in summary.actionable_takeaways) or "- （示唆なし）"
    outline_md = "\n".join(structured.note_outline) if structured.note_outline else "（アウトライン未生成）"

    content = f"""# {summary.title}

> **出典**: [{summary.source}]({summary.url})

---

## はじめに

{structured.core_insight if structured.core_insight else summary.summary_ja[:200]}

（ダミー下書き – ANTHROPIC_API_KEY を設定すると本格的な下書きが生成されます）

---

## 要点整理

{key_points_md}

---

## 背景と文脈

**切り口**: {structured.angle}
**想定読者**: {structured.audience}

{summary.summary_ja}

---

## 実装・活用への示唆

{takeaways_md}

**具体的なアクション**: {structured.implementation_hint}

---

<!-- ここから有料コンテンツ候補 -->
## 深掘り：なぜこれが重要なのか（有料ゾーン案）

ここには、より詳細な技術解説や業界分析、具体的な実装ステップを記載します。

---

## まとめ

- {summary.key_points[0] if summary.key_points else 'AIの進化は継続している'}
- 継続的にキャッチアップすることが重要

---

## 出典・参考

- 元記事: [{summary.source}]({summary.url})
"""

    title = summary.title.replace("【要約】", "").strip()
    return NoteDraft(title=title, content_md=content)


# ---------------------------------------------------------------------------
# API-based generation
# ---------------------------------------------------------------------------

def _api_note_draft(
    summary: Summary,
    structured: StructuredContent,
    settings: dict,
) -> NoteDraft:
    from anthropic import Anthropic  # noqa: PLC0415

    template = read_text(_PROMPT_PATH)
    prompt = template.format(
        title=summary.title,
        source=summary.source,
        url=summary.url,
        summary_ja=summary.summary_ja,
        key_points="\n".join(f"- {p}" for p in summary.key_points),
        actionable_takeaways="\n".join(f"- {p}" for p in summary.actionable_takeaways),
        angle=structured.angle,
        audience=structured.audience,
        core_insight=structured.core_insight,
        implementation_hint=structured.implementation_hint,
        note_outline="\n".join(structured.note_outline),
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
    raw = message.content[0].text.strip()

    # Extract title from first H1 heading if present
    title_match = re.match(r"^#\s+(.+)", raw)
    if title_match:
        note_title = title_match.group(1).strip()
    else:
        note_title = summary.title.replace("【要約】", "").strip()

    return NoteDraft(title=note_title, content_md=raw)


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def generate_note_draft(
    summary: Summary,
    structured: StructuredContent,
    settings: dict,
) -> NoteDraft:
    """Generate a note.com Markdown draft for *summary*.

    Args:
        summary: The :class:`~models.Summary` for this article.
        structured: The :class:`~models.StructuredContent` for this article.
        settings: Loaded ``config/settings.yaml`` dict.

    Returns:
        A :class:`~models.NoteDraft` with title and Markdown content.
    """
    if not os.getenv("ANTHROPIC_API_KEY"):
        logger.warning(
            "ANTHROPIC_API_KEY not set – using dummy note draft for '%s'", summary.title
        )
        return _dummy_note_draft(summary, structured)

    try:
        draft = _api_note_draft(summary, structured, settings)
        logger.info("Generated note draft via Claude API for '%s'", summary.title)
        return draft
    except Exception as exc:
        logger.error(
            "API note generation failed for '%s': %s – using dummy.", summary.title, exc
        )
        return _dummy_note_draft(summary, structured)
