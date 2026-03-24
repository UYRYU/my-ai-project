"""Export approved note drafts to Markdown files.

Each approved note item is written to ``data/drafts/notes/`` as a ``.md`` file.
The filename uses a timestamp and sanitised title.

note.com API integration is intentionally NOT implemented – this module only
produces local Markdown files for pasting into the note editor or future
automated posting.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from models import ApprovalItem
from review.approval_queue import ApprovalQueue
from utils.fileio import write_text, ensure_dir
from utils.logger import setup_logger

logger = setup_logger(__name__)

_DEFAULT_OUTPUT_DIR = Path("data/drafts/notes")


def _sanitise_filename(text: str, max_len: int = 50) -> str:
    """Convert *text* to a safe filename fragment."""
    text = re.sub(r'[\\/:*?"<>|【】「」『』（）()【】]', "_", text)
    text = re.sub(r"\s+", "_", text)
    text = text[:max_len].rstrip("_")
    return text or "note"


def export_approved_notes(
    queue: ApprovalQueue,
    output_dir: str | Path = _DEFAULT_OUTPUT_DIR,
) -> list[Path]:
    """Write all approved note items to Markdown files in *output_dir*.

    Items whose files already exist are skipped (idempotent).

    Args:
        queue: The :class:`~review.approval_queue.ApprovalQueue` instance.
        output_dir: Directory to write Markdown files into.

    Returns:
        List of :class:`~pathlib.Path` objects for newly written files.
    """
    out_dir = ensure_dir(output_dir)
    approved = [item for item in queue.get_approved() if item.item_type == "note"]

    if not approved:
        logger.info("No approved note drafts to export.")
        return []

    written: list[Path] = []
    for item in approved:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        safe_title = _sanitise_filename(item.title)
        filename = out_dir / f"{ts}_{safe_title}.md"

        if filename.exists():
            logger.debug("Skipping existing file: %s", filename)
            continue

        content_md = item.content.get("content_md", "")
        # Prepend YAML front matter with metadata
        front_matter = (
            "---\n"
            f"title: \"{item.title}\"\n"
            f"source: \"{item.source_name}\"\n"
            f"source_url: \"{item.source_url}\"\n"
            f"created_at: \"{item.created_at}\"\n"
            f"status: draft\n"
            "---\n\n"
        )
        write_text(filename, front_matter + content_md)
        logger.info("Exported note draft: %s", filename.name)
        written.append(filename)

    if written:
        print(f"note下書き {len(written)}件 を {out_dir} に出力しました。")
    else:
        print("新規エクスポートするnote下書きはありませんでした。")

    return written
