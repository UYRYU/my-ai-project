"""
Polymarket Tracker - トレーダー別成績管理モジュール
ペーパートレードの成績をトレーダー別に集計し、
負けてるトレーダーを自動で追跡から除外する。
"""

import json
import os
from typing import Dict, List, Set

from loguru import logger

import risk


# トレーダー成績の評価設定
MIN_TRADES_TO_EVAL = 5       # これ以上のトレード数があれば評価対象
MIN_WIN_RATE = 0.30          # これ未満の勝率ならブラックリスト
BLACKLIST_PATH = "data/trader_blacklist.json"
STATS_PATH = "data/trader_stats.json"


def compute_trader_stats() -> Dict[str, dict]:
    """
    ペーパートレード履歴からトレーダー別の成績を集計する。

    Returns:
        {
            "trader_name": {
                "total": N, "wins": N, "losses": N, "open": N,
                "win_rate": 0.xx, "pnl": +xx.xx,
                "verdict": "GOOD" / "BAD" / "NOT_ENOUGH_DATA"
            }
        }
    """
    trades = risk._load_paper_trades()
    stats: Dict[str, dict] = {}

    for t in trades:
        trader = t.get("trader", "unknown")
        if trader not in stats:
            stats[trader] = {
                "total": 0, "wins": 0, "losses": 0, "open": 0, "pnl": 0.0,
            }

        stats[trader]["total"] += 1
        if t["status"] == "open":
            stats[trader]["open"] += 1
        elif t.get("result") == 1:
            stats[trader]["wins"] += 1
            stats[trader]["pnl"] += t.get("pnl", 0)
        elif t.get("result") == 0:
            stats[trader]["losses"] += 1
            stats[trader]["pnl"] += t.get("pnl", 0)

    # 勝率と判定を追加
    for trader, s in stats.items():
        decided = s["wins"] + s["losses"]
        s["decided"] = decided
        s["win_rate"] = s["wins"] / decided if decided > 0 else 0.0

        if decided < MIN_TRADES_TO_EVAL:
            s["verdict"] = "NOT_ENOUGH_DATA"
        elif s["win_rate"] < MIN_WIN_RATE or s["pnl"] < 0:
            s["verdict"] = "BAD"
        else:
            s["verdict"] = "GOOD"

    # 保存
    os.makedirs(os.path.dirname(STATS_PATH) or ".", exist_ok=True)
    with open(STATS_PATH, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)

    return stats


def update_blacklist() -> Set[str]:
    """
    負けてるトレーダーをブラックリストに追加する。

    Returns:
        ブラックリストに載っているトレーダー名のセット
    """
    stats = compute_trader_stats()
    blacklist: Set[str] = set()

    for trader, s in stats.items():
        if s["verdict"] == "BAD":
            blacklist.add(trader)

    # 保存
    with open(BLACKLIST_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(list(blacklist)), f, indent=2, ensure_ascii=False)

    return blacklist


def load_blacklist() -> Set[str]:
    """ブラックリストを読み込む"""
    if not os.path.exists(BLACKLIST_PATH):
        return set()
    try:
        with open(BLACKLIST_PATH, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def is_blacklisted(trader: str) -> bool:
    """指定トレーダーがブラックリストに載っているか"""
    return trader in load_blacklist()


def print_trader_stats() -> None:
    """トレーダー別成績を表示する"""
    stats = compute_trader_stats()
    if not stats:
        print("\nペーパートレード記録がありません\n")
        return

    # 判定で分類、負け損益順でソート
    sorted_items = sorted(
        stats.items(),
        key=lambda x: (x[1]["verdict"], -x[1]["pnl"]),
    )

    print("\n" + "=" * 80)
    print(" トレーダー別成績")
    print("=" * 80)
    print(f"{'トレーダー':<22}{'全':>5}{'勝':>5}{'負':>5}{'オ':>5}{'勝率':>8}{'損益':>10}  判定")
    print("-" * 80)

    for trader, s in sorted_items:
        name = (trader[:20] + "..") if len(trader) > 22 else trader
        win_rate = f"{s['win_rate']*100:.1f}%" if s["decided"] > 0 else "-"
        verdict = s["verdict"]
        # 色分け (verdict)
        mark = {"GOOD": "✓", "BAD": "✗", "NOT_ENOUGH_DATA": "?"}.get(verdict, "-")
        print(
            f"{name:<22}"
            f"{s['total']:>5}"
            f"{s['wins']:>5}"
            f"{s['losses']:>5}"
            f"{s['open']:>5}"
            f"{win_rate:>8}"
            f"{s['pnl']:>+10.2f}  "
            f"{mark} {verdict}"
        )

    # サマリー
    n_good = sum(1 for s in stats.values() if s["verdict"] == "GOOD")
    n_bad = sum(1 for s in stats.values() if s["verdict"] == "BAD")
    n_unknown = sum(1 for s in stats.values() if s["verdict"] == "NOT_ENOUGH_DATA")

    print("-" * 80)
    print(f" GOOD: {n_good} 人  |  BAD: {n_bad} 人  |  データ不足: {n_unknown} 人")
    print(f" 評価条件: 決着 {MIN_TRADES_TO_EVAL} 件以上 & 勝率 {MIN_WIN_RATE*100:.0f}% 未満 or 損益マイナス → BAD")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    update_blacklist()
    print_trader_stats()
