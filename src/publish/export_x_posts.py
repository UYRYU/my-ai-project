"""Export approved X post drafts to plain text files.

Each approved X post is written to ``data/drafts/x_posts/`` as a ``.txt`` file.
The filename includes a timestamp and a sanitised title so files are easy to
identify and sort.

Real X API integration is intentionally NOT implemented here – this module
only writes local files for human review before manual or future automated
posting.
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

_DEFAULT_OUTPUT_DIR = Path("data/drafts/x_posts")


def _sanitise_filename(text: str, max_len: int = 40) -> str:
    """Convert *text* to a safe filename fragment."""
    text = re.sub(r'[\\/:*?"<>|【】「」『』（）()【】]', "_", text)
    text = re.sub(r"\s+", "_", text)
    text = text[:max_len].rstrip("_")
    return text or "post"


def _build_post_text(item: ApprovalItem) -> str:
    """Assemble the final post text from the stored content dict."""
    c = item.content
    parts: list[str] = []
    for key in ("hook", "body", "closing", "source_reference"):
        val = c.get(key, "").strip()
        if val:
            parts.append(val)
    return "\n\n".join(parts)


def export_approved_x_posts(
    queue: ApprovalQueue,
    output_dir: str | Path = _DEFAULT_OUTPUT_DIR,
) -> list[Path]:
    """Write all approved X post items to text files in *output_dir*.

    Items whose files already exist are skipped (idempotent).

    Args:
        queue: The :class:`~review.approval_queue.ApprovalQueue` instance.
        output_dir: Directory to write post files into.

    Returns:
        List of :class:`~pathlib.Path` objects for newly written files.
    """
    out_dir = ensure_dir(output_dir)
    approved = [item for item in queue.get_approved() if item.item_type == "x_post"]

    if not approved:
        logger.info("No approved X posts to export.")
        return []

    written: list[Path] = []
    for item in approved:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        safe_title = _sanitise_filename(item.title)
        filename = out_dir / f"{ts}_{safe_title}.txt"

        if filename.exists():
            logger.debug("Skipping existing file: %s", filename)
            continue

        post_text = _build_post_text(item)
        meta = (
            f"# X投稿案\n"
            f"# ソース: {item.source_name}\n"
            f"# URL: {item.source_url}\n"
            f"# 作成: {item.created_at}\n"
            f"# 文字数: {len(post_text)}\n"
            f"{'─'*60}\n\n"
        )
        write_text(filename, meta + post_text)
        logger.info("Exported X post: %s (%d chars)", filename.name, len(post_text))
        written.append(filename)

    if written:
        print(f"X投稿案 {len(written)}件 を {out_dir} に出力しました。")
    else:
        print("新規エクスポートするX投稿案はありませんでした。")

    return written
