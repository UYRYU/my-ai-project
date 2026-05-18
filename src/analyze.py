"""Offline Claude-powered analyst.

Claude is too slow and too expensive for the hot trading loop. Instead,
run this command once a day against `trades.jsonl` to review what the
bot saw, what it acted on, and whether the strategy is healthy.

Usage:
    python -m src.analyze trades.jsonl
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from anthropic import Anthropic


MODEL = "claude-opus-4-7"


def _load(path: Path) -> list[dict]:
    rows = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _summary(rows: list[dict]) -> dict:
    event_counts = Counter(r.get("event", "?") for r in rows)
    edges = [r["edge"] for r in rows if r.get("event") == "opportunity" and "edge" in r]
    rejects = Counter(
        r.get("event") for r in rows if r.get("event", "").startswith("rejected_")
    )
    return {
        "total_rows": len(rows),
        "events": dict(event_counts),
        "opportunities": len(edges),
        "avg_edge": sum(edges) / len(edges) if edges else 0.0,
        "max_edge": max(edges) if edges else 0.0,
        "rejections": dict(rejects),
    }


def analyze(path: Path, api_key: str) -> None:
    rows = _load(path)
    if not rows:
        print(f"{path}: empty")
        return

    summary = _summary(rows)
    print("== bot activity summary ==")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print()

    if not api_key:
        print("(ANTHROPIC_API_KEY 未設定 — Claude 分析はスキップ)")
        return

    # Feed Claude the summary + a sample of raw events. Put the frozen
    # instruction in the cached system prompt; the volatile data goes
    # in the user message so the prefix stays stable across daily runs.
    recent_sample = rows[-200:]
    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        thinking={"type": "adaptive"},
        system=[
            {
                "type": "text",
                "text": (
                    "あなたはアービトラージボットのパフォーマンスアナリストです。"
                    "ボットのイベントログ要約と最近のイベントサンプルが与えられます。"
                    "以下を日本語で簡潔に答えてください:\n"
                    "1) ボットは健全に動いているか(Yes/No と理由)\n"
                    "2) よく起きている拒否理由とその意味\n"
                    "3) 調整すべきパラメータ(min_edge, spread filter, etc.)\n"
                    "4) 注意すべき異常パターン\n"
                    "推測は最小限、データに基づいてください。"
                ),
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": (
                    f"SUMMARY:\n{json.dumps(summary, ensure_ascii=False)}\n\n"
                    f"RECENT_EVENTS:\n"
                    + "\n".join(json.dumps(r, ensure_ascii=False) for r in recent_sample)
                ),
            }
        ],
    )
    print("== Claude analyst ==")
    for block in response.content:
        if block.type == "text":
            print(block.text)


def main() -> int:
    import os
    from dotenv import load_dotenv

    load_dotenv()
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("trades.jsonl")
    if not path.exists():
        print(f"{path} not found")
        return 1
    analyze(path, os.environ.get("ANTHROPIC_API_KEY", ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
