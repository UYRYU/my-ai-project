"""Approval queue: manage X post and note drafts awaiting human review.

The queue is a JSON file (default: ``data/state/approval_queue.json``).
Each item carries a ``status`` of:
  - ``"pending"``  – awaiting review
  - ``"approved"`` – human approved; ready for export
  - ``"rejected"`` – human rejected; will not be exported

CLI usage (called from main.py --approve):
  Iterates pending items, prints each one, and prompts y/n/skip.
"""
from __future__ import annotations

import dataclasses
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from models import ApprovalItem
from utils.fileio import read_json, write_json
from utils.logger import setup_logger

logger = setup_logger(__name__)


class ApprovalQueue:
    """Persistent approval queue backed by a JSON file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._items: list[dict[str, Any]] = []
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        data = read_json(self.path)
        self._items = data if isinstance(data, list) else []
        logger.debug("Loaded %d items from approval queue at %s", len(self._items), self.path)

    def _save(self) -> None:
        write_json(self.path, self._items)
        logger.debug("Saved %d items to approval queue at %s", len(self._items), self.path)

    # ------------------------------------------------------------------
    # Adding items
    # ------------------------------------------------------------------

    def add_item(
        self,
        article_id: str,
        item_type: str,
        title: str,
        content: dict[str, Any],
        source_name: str,
        source_url: str,
    ) -> ApprovalItem:
        """Add a new item with ``status="pending"`` and return it.

        Duplicate detection: if an item with the same ``article_id`` and
        ``item_type`` already exists (any status), it is skipped and the
        existing item is returned.
        """
        for raw in self._items:
            if raw.get("article_id") == article_id and raw.get("item_type") == item_type:
                logger.debug(
                    "Item already in queue: article_id=%s type=%s – skipping.", article_id, item_type
                )
                return self._to_model(raw)

        item = ApprovalItem(
            id=str(uuid.uuid4()),
            article_id=article_id,
            item_type=item_type,
            title=title,
            content=content,
            status="pending",
            created_at=datetime.now(timezone.utc).isoformat(),
            source_name=source_name,
            source_url=source_url,
        )
        self._items.append(dataclasses.asdict(item))
        self._save()
        logger.info("Added %s item to queue: '%s'", item_type, title)
        return item

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def get_all(self) -> list[ApprovalItem]:
        return [self._to_model(r) for r in self._items]

    def get_pending(self) -> list[ApprovalItem]:
        return [self._to_model(r) for r in self._items if r.get("status") == "pending"]

    def get_approved(self) -> list[ApprovalItem]:
        return [self._to_model(r) for r in self._items if r.get("status") == "approved"]

    def get_rejected(self) -> list[ApprovalItem]:
        return [self._to_model(r) for r in self._items if r.get("status") == "rejected"]

    # ------------------------------------------------------------------
    # Status updates
    # ------------------------------------------------------------------

    def approve(self, item_id: str) -> bool:
        """Mark the item with *item_id* as approved.  Returns True on success."""
        return self._set_status(item_id, "approved")

    def reject(self, item_id: str) -> bool:
        """Mark the item with *item_id* as rejected.  Returns True on success."""
        return self._set_status(item_id, "rejected")

    def _set_status(self, item_id: str, status: str) -> bool:
        for raw in self._items:
            if raw.get("id") == item_id:
                raw["status"] = status
                self._save()
                logger.info("Item %s → status=%s", item_id, status)
                return True
        logger.warning("Item not found in queue: %s", item_id)
        return False

    # ------------------------------------------------------------------
    # Summary stats
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, int]:
        total = len(self._items)
        pending = sum(1 for r in self._items if r.get("status") == "pending")
        approved = sum(1 for r in self._items if r.get("status") == "approved")
        rejected = sum(1 for r in self._items if r.get("status") == "rejected")
        return {"total": total, "pending": pending, "approved": approved, "rejected": rejected}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_model(raw: dict[str, Any]) -> ApprovalItem:
        return ApprovalItem(
            id=raw.get("id", ""),
            article_id=raw.get("article_id", ""),
            item_type=raw.get("item_type", ""),
            title=raw.get("title", ""),
            content=raw.get("content", {}),
            status=raw.get("status", "pending"),
            created_at=raw.get("created_at", ""),
            source_name=raw.get("source_name", ""),
            source_url=raw.get("source_url", ""),
        )


# ---------------------------------------------------------------------------
# Interactive CLI review
# ---------------------------------------------------------------------------

def run_interactive_review(queue: ApprovalQueue) -> None:
    """Interactively review pending items via stdin prompts.

    Commands:
      y / yes   → approve
      n / no    → reject
      s / skip  → leave as pending
      q / quit  → stop reviewing
    """
    pending = queue.get_pending()
    if not pending:
        print("承認待ちのアイテムはありません。")
        return

    print(f"\n{'='*60}")
    print(f"承認待ちアイテム: {len(pending)}件")
    print(f"{'='*60}\n")

    for idx, item in enumerate(pending, 1):
        print(f"\n[{idx}/{len(pending)}] ─── {item.item_type.upper()} ───────────────")
        print(f"  タイトル : {item.title}")
        print(f"  ソース   : {item.source_name} ({item.source_url})")
        print(f"  作成日時 : {item.created_at}")
        print()

        if item.item_type == "x_post":
            content = item.content
            print("  ─ 投稿案 ─")
            print(f"  {content.get('hook', '')}")
            print(f"  {content.get('body', '')}")
            print(f"  {content.get('closing', '')}")
            print(f"  {content.get('source_reference', '')}")
        elif item.item_type == "note":
            md = item.content.get("content_md", "")
            preview = "\n  ".join(md.splitlines()[:10])
            print("  ─ note 下書き（先頭10行）─")
            print(f"  {preview}")
            if len(md.splitlines()) > 10:
                print("  …（続きは data/drafts/ を参照）")

        print()
        while True:
            ans = input("  [y=承認 / n=却下 / s=スキップ / q=終了] > ").strip().lower()
            if ans in ("y", "yes"):
                queue.approve(item.id)
                print("  ✓ 承認しました")
                break
            elif ans in ("n", "no"):
                queue.reject(item.id)
                print("  ✗ 却下しました")
                break
            elif ans in ("s", "skip", ""):
                print("  → スキップ")
                break
            elif ans in ("q", "quit"):
                print("\nレビューを中断しました。")
                return
            else:
                print("  入力が認識できません。y / n / s / q のいずれかを入力してください。")

    stats = queue.stats()
    print(f"\nレビュー完了: 承認={stats['approved']} / 却下={stats['rejected']} / 保留={stats['pending']}")
