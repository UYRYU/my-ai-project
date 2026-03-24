"""AI News Automation – main entry point.

Usage:
  python src/main.py           # Run full pipeline (fetch → generate → queue)
  python src/main.py --approve # Interactively review pending queue items
  python src/main.py --export  # Export approved items to files
  python src/main.py --all     # Run pipeline then approve then export
"""
from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup: ensure src/ is importable as the root package directory
# ---------------------------------------------------------------------------
SRC_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SRC_DIR.parent
sys.path.insert(0, str(SRC_DIR))

# Load .env if python-dotenv is available (silently skip if not)
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Imports from this project
# ---------------------------------------------------------------------------
from fetch.fetch_sources import load_sources, fetch_source
from fetch.parse_article import parse_article
from process.summarize import summarize_article
from process.structure import structure_content
from process.dedupe import check_duplicate, save_processed_summary
from generate.x_writer import generate_x_posts
from generate.note_writer import generate_note_draft
from review.approval_queue import ApprovalQueue, run_interactive_review
from publish.export_x_posts import export_approved_x_posts
from publish.export_note_md import export_approved_notes
from utils.fileio import read_yaml, write_json, ensure_dir
from utils.logger import setup_logger

logger = setup_logger("main", log_dir=str(PROJECT_ROOT / "data" / "logs"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_settings() -> dict:
    path = PROJECT_ROOT / "config" / "settings.yaml"
    return read_yaml(path)


def _queue_path(settings: dict) -> Path:
    rel = settings.get("approval_queue", {}).get("path", "data/state/approval_queue.json")
    return PROJECT_ROOT / rel


def _save_raw_article(article, settings: dict) -> None:
    raw_dir = ensure_dir(PROJECT_ROOT / settings.get("output", {}).get("raw_dir", "data/raw"))
    path = raw_dir / f"{article.id}.json"
    write_json(path, dataclasses.asdict(article))


def _save_processed(summary, structured, settings: dict) -> None:
    proc_dir = ensure_dir(
        PROJECT_ROOT / settings.get("output", {}).get("processed_dir", "data/processed")
    )
    data = {"summary": dataclasses.asdict(summary), "structured": dataclasses.asdict(structured)}
    path = proc_dir / f"{summary.article_id}.json"
    write_json(path, data)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_pipeline(settings: dict) -> int:
    """Execute the full fetch → generate → queue pipeline.

    Returns the number of items added to the queue.
    """
    logger.info("=" * 60)
    logger.info("AI News Automation Pipeline – START")
    logger.info("=" * 60)

    queue = ApprovalQueue(_queue_path(settings))
    items_added = 0

    # 1. Load sources
    sources_path = PROJECT_ROOT / "sources.yaml"
    sources = load_sources(str(sources_path))
    enabled = [s for s in sources if s.enabled]
    logger.info("Enabled sources: %d / %d", len(enabled), len(sources))

    for source in enabled:
        logger.info("─── Processing source: %s ───", source.name)

        # 2. Fetch raw articles
        raw_dicts = fetch_source(source)
        if not raw_dicts:
            logger.warning("No articles fetched from '%s'", source.name)
            continue

        for raw in raw_dicts:
            # 3. Parse / normalise
            article = parse_article(raw)
            _save_raw_article(article, settings)

            # 4. Summarise
            summary = summarize_article(article, settings)

            # 5. Deduplicate
            is_dup, score = check_duplicate(summary, settings)
            if is_dup:
                logger.info(
                    "Skipping duplicate article '%s' (similarity=%.2f)", article.title, score
                )
                continue

            # 6. Structure
            structured = structure_content(summary, settings)
            _save_processed(summary, structured, settings)

            # 7. Generate X posts
            x_posts = generate_x_posts(summary, structured, settings)
            for i, post in enumerate(x_posts, 1):
                queue.add_item(
                    article_id=f"{article.id}_x{i}",
                    item_type="x_post",
                    title=f"{summary.title} – X案{i}",
                    content=dataclasses.asdict(post),
                    source_name=summary.source,
                    source_url=summary.url,
                )
                items_added += 1

            # 8. Generate note draft
            note = generate_note_draft(summary, structured, settings)
            queue.add_item(
                article_id=f"{article.id}_note",
                item_type="note",
                title=note.title,
                content={"title": note.title, "content_md": note.content_md},
                source_name=summary.source,
                source_url=summary.url,
            )
            items_added += 1

            # 9. Persist summary to dedup store
            save_processed_summary(summary, settings)

    # Summary
    stats = queue.stats()
    logger.info("Pipeline complete.")
    logger.info(
        "Queue stats: total=%d | pending=%d | approved=%d | rejected=%d",
        stats["total"],
        stats["pending"],
        stats["approved"],
        stats["rejected"],
    )

    print("\n" + "=" * 60)
    print("パイプライン完了")
    print(f"  追加アイテム : {items_added}")
    print(f"  承認待ち     : {stats['pending']}")
    print(f"  承認済み     : {stats['approved']}")
    print(f"  却下         : {stats['rejected']}")
    print("=" * 60)
    print("\n次のステップ:")
    print("  python src/main.py --approve   ← 内容を確認して承認/却下")
    print("  python src/main.py --export    ← 承認済みアイテムをファイル出力")

    return items_added


# ---------------------------------------------------------------------------
# Approve mode
# ---------------------------------------------------------------------------

def run_approve(settings: dict) -> None:
    queue = ApprovalQueue(_queue_path(settings))
    run_interactive_review(queue)


# ---------------------------------------------------------------------------
# Export mode
# ---------------------------------------------------------------------------

def run_export(settings: dict) -> None:
    queue = ApprovalQueue(_queue_path(settings))

    x_dir = PROJECT_ROOT / settings.get("output", {}).get("drafts_dir", "data/drafts") / "x_posts"
    n_dir = PROJECT_ROOT / settings.get("output", {}).get("drafts_dir", "data/drafts") / "notes"

    x_files = export_approved_x_posts(queue, output_dir=x_dir)
    n_files = export_approved_notes(queue, output_dir=n_dir)

    total = len(x_files) + len(n_files)
    if total:
        print(f"\n合計 {total}件 のファイルを出力しました。")
    else:
        print("\n出力する承認済みアイテムがありません。--approve で承認してください。")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="AI海外情報の自動収集・要約・下書き生成ツール",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python src/main.py            # フルパイプライン実行\n"
            "  python src/main.py --approve  # 承認キューのレビュー\n"
            "  python src/main.py --export   # 承認済みアイテムのエクスポート\n"
            "  python src/main.py --all      # パイプライン→承認→エクスポート\n"
        ),
    )
    parser.add_argument(
        "--approve",
        action="store_true",
        help="承認キューをインタラクティブにレビューする",
    )
    parser.add_argument(
        "--export",
        action="store_true",
        help="承認済みアイテムをファイルに出力する",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="パイプライン・承認・エクスポートをまとめて実行する",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    settings = _load_settings()

    if args.all:
        run_pipeline(settings)
        run_approve(settings)
        run_export(settings)
    elif args.approve:
        run_approve(settings)
    elif args.export:
        run_export(settings)
    else:
        run_pipeline(settings)


if __name__ == "__main__":
    main()
