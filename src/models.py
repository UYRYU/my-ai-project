"""Shared data models used across the pipeline.

All models are plain dataclasses so they can be trivially serialised with
``dataclasses.asdict()`` and deserialised from JSON dicts.
"""
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Source (from sources.yaml)
# ---------------------------------------------------------------------------

@dataclass
class Source:
    name: str
    platform: str           # "web" | "rss" | "x"
    handle_or_url: str
    enabled: bool
    priority: int


# ---------------------------------------------------------------------------
# Raw article (fetched + parsed)
# ---------------------------------------------------------------------------

@dataclass
class RawArticle:
    id: str                 # UUID or hash-based unique ID
    title: str
    body: str               # Full extracted body text
    url: str
    date: str               # ISO-8601 string, or empty string if unknown
    source_name: str
    platform: str


# ---------------------------------------------------------------------------
# Japanese summary
# ---------------------------------------------------------------------------

@dataclass
class Summary:
    article_id: str
    title: str
    source: str
    url: str
    summary_ja: str
    key_points: list[str] = field(default_factory=list)
    actionable_takeaways: list[str] = field(default_factory=list)
    quoted_claims_to_verify: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Structured content for Japanese audience
# ---------------------------------------------------------------------------

@dataclass
class StructuredContent:
    article_id: str
    angle: str              # 切り口・視点
    audience: str           # 想定読者
    core_insight: str       # 核心的な洞察
    implementation_hint: str  # 実装・活用への示唆
    note_outline: list[str] = field(default_factory=list)   # note記事の章立て案
    x_hooks: list[str] = field(default_factory=list)        # X投稿のフック案


# ---------------------------------------------------------------------------
# X (Twitter) post draft
# ---------------------------------------------------------------------------

@dataclass
class XPost:
    hook: str               # 冒頭のフック（注意を引く一言）
    body: str               # 本文
    closing: str            # 締めの一言
    source_reference: str   # 出典表記

    def to_text(self) -> str:
        """Combine all parts into a single post string."""
        parts = [self.hook, self.body, self.closing, self.source_reference]
        return "\n\n".join(p for p in parts if p)

    def char_count(self) -> int:
        return len(self.to_text())


# ---------------------------------------------------------------------------
# note draft
# ---------------------------------------------------------------------------

@dataclass
class NoteDraft:
    title: str
    content_md: str         # Full Markdown body


# ---------------------------------------------------------------------------
# Approval queue item
# ---------------------------------------------------------------------------

@dataclass
class ApprovalItem:
    id: str                 # UUID
    article_id: str
    item_type: str          # "x_post" | "note"
    title: str
    content: dict[str, Any]   # Serialised XPost or NoteDraft
    status: str             # "pending" | "approved" | "rejected"
    created_at: str         # ISO-8601
    source_name: str
    source_url: str
