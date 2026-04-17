"""
Polymarket Tracker - 自動チューニングモジュール
ペーパートレードの結果を分析し、戦略パラメータを自動調整する。

自動調整の内容:
  1. 負けてるオッズ帯を自動除外 (例: 0.40-0.50 が常に負けてれば除外)
  2. 負けてるトレーダーを自動ブラックリスト (trader_stats.py と連携)
  3. 勝ってるトレーダーをホワイトリスト化 (即発火対象)
  4. スポーツ別に不調なら除外候補に
"""

import json
import os
from collections import defaultdict
from typing import Dict, List

from loguru import logger


# ===== 自動除外の基準 =====
MIN_DECIDED_TO_JUDGE = 5      # これ以上決着してれば判定対象
BAD_WIN_RATE = 0.35           # これ未満で負けと判定
GOOD_WIN_RATE = 0.60          # これ以上で勝ちと判定
BAD_PNL_THRESHOLD = -5.0      # -$5以下で除外

# ===== ファイルパス =====
PAPER_TRADES_PATH = "data/paper_trades.json"
BLOCKED_BANDS_PATH = "data/blocked_bands.json"
BLOCKED_SPORTS_PATH = "data/blocked_sports.json"
TUNE_LOG_PATH = "data/auto_tune_log.json"


ODDS_BANDS = [
    ("0.35-0.40", 0.35, 0.40),
    ("0.40-0.50", 0.40, 0.50),
    ("0.50-0.60", 0.50, 0.60),
    ("0.60-0.70", 0.60, 0.70),
    ("0.70-0.80", 0.70, 0.80),
]


def _load_trades() -> list:
    if not os.path.exists(PAPER_TRADES_PATH):
        return []
    try:
        with open(PAPER_TRADES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _band_of(odds: float) -> str:
    for label, lo, hi in ODDS_BANDS:
        if lo <= odds < hi:
            return label
    return "out"


def _detect_sport(title: str) -> str:
    if not title:
        return "OTHER"
    upper = title.upper()
    if "NBA" in upper or "WARRIORS" in upper or "LAKERS" in upper or "CELTICS" in upper \
       or "NUGGETS" in upper or "HEAT" in upper or "HORNETS" in upper or "SUNS" in upper:
        return "NBA"
    if "NHL" in upper or "BRUINS" in upper or "CANUCKS" in upper or "FLAMES" in upper:
        return "NHL"
    if "MLB" in upper or "YANKEES" in upper or "DODGERS" in upper or "RED SOX" in upper \
       or "METS" in upper or "ORIOLES" in upper:
        return "MLB"
    if "COUNTER-STRIKE" in upper or "CS:" in upper or "CS2" in upper:
        return "CS2"
    if "LOL" in upper or "DOTA" in upper or "VALORANT" in upper or "ESPORTS" in upper:
        return "ESPORTS"
    if "FC" in upper or "CHAMPIONS LEAGUE" in upper or "PSG" in upper \
       or "ARSENAL" in upper or "REAL MADRID" in upper:
        return "SOCCER"
    if "OPEN" in upper or "BMW" in upper or "ATP" in upper or "WTA" in upper:
        return "TENNIS"
    return "OTHER"


def tune_odds_bands() -> Dict[str, dict]:
    """オッズ帯別の成績を見て、負けてる帯を除外リストに追加"""
    trades = _load_trades()
    closed = [t for t in trades if t.get("status") == "closed"]

    stats_by_band: Dict[str, dict] = {}
    for label, lo, hi in ODDS_BANDS:
        band_trades = [t for t in closed if lo <= t.get("odds", 0) < hi]
        wins = [t for t in band_trades if t.get("result") == 1]
        pnl = sum(t.get("pnl", 0) for t in band_trades)
        stats_by_band[label] = {
            "decided": len(band_trades),
            "wins": len(wins),
            "win_rate": len(wins) / len(band_trades) if band_trades else 0,
            "pnl": pnl,
            "verdict": None,
        }

    blocked = []
    for label, s in stats_by_band.items():
        if s["decided"] >= MIN_DECIDED_TO_JUDGE:
            if s["win_rate"] < BAD_WIN_RATE or s["pnl"] < BAD_PNL_THRESHOLD:
                s["verdict"] = "BLOCKED"
                blocked.append(label)
            elif s["win_rate"] >= GOOD_WIN_RATE:
                s["verdict"] = "GOOD"
            else:
                s["verdict"] = "OK"
        else:
            s["verdict"] = "NOT_ENOUGH_DATA"

    # 保存
    os.makedirs(os.path.dirname(BLOCKED_BANDS_PATH) or ".", exist_ok=True)
    with open(BLOCKED_BANDS_PATH, "w", encoding="utf-8") as f:
        json.dump(blocked, f, indent=2)

    return stats_by_band


def tune_sports() -> Dict[str, dict]:
    """スポーツ別に負けてるものを除外"""
    trades = _load_trades()
    closed = [t for t in trades if t.get("status") == "closed"]

    by_sport = defaultdict(list)
    for t in closed:
        sport = _detect_sport(t.get("market_title", ""))
        by_sport[sport].append(t)

    stats: Dict[str, dict] = {}
    blocked = []
    for sport, group in by_sport.items():
        wins = [t for t in group if t.get("result") == 1]
        pnl = sum(t.get("pnl", 0) for t in group)
        decided = len(group)
        win_rate = len(wins) / decided if decided else 0

        verdict = "NOT_ENOUGH_DATA"
        if decided >= MIN_DECIDED_TO_JUDGE:
            if win_rate < BAD_WIN_RATE or pnl < BAD_PNL_THRESHOLD:
                verdict = "BLOCKED"
                blocked.append(sport)
            elif win_rate >= GOOD_WIN_RATE:
                verdict = "GOOD"
            else:
                verdict = "OK"

        stats[sport] = {
            "decided": decided,
            "wins": len(wins),
            "win_rate": win_rate,
            "pnl": pnl,
            "verdict": verdict,
        }

    os.makedirs(os.path.dirname(BLOCKED_SPORTS_PATH) or ".", exist_ok=True)
    with open(BLOCKED_SPORTS_PATH, "w", encoding="utf-8") as f:
        json.dump(blocked, f, indent=2)

    return stats


def load_blocked_bands() -> List[str]:
    """除外されたオッズ帯を読み込む"""
    if not os.path.exists(BLOCKED_BANDS_PATH):
        return []
    try:
        with open(BLOCKED_BANDS_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return []


def load_blocked_sports() -> List[str]:
    """除外されたスポーツを読み込む"""
    if not os.path.exists(BLOCKED_SPORTS_PATH):
        return []
    try:
        with open(BLOCKED_SPORTS_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return []


def is_blocked_odds(odds: float) -> bool:
    """指定オッズが除外帯に該当するか"""
    blocked = load_blocked_bands()
    for label, lo, hi in ODDS_BANDS:
        if label in blocked and lo <= odds < hi:
            return True
    return False


def is_blocked_sport(title: str) -> bool:
    """指定タイトルから推定されるスポーツが除外済みか"""
    blocked = load_blocked_sports()
    sport = _detect_sport(title)
    return sport in blocked


def run_auto_tune() -> dict:
    """
    全自動チューニングを実行する。
    トレーダー除外 (trader_stats) + オッズ帯除外 + スポーツ除外 を一括で。
    """
    from trader_stats import update_blacklist, update_whitelist

    logger.info("[auto_tune] 自動調整を開始")

    blacklist = update_blacklist()
    whitelist = update_whitelist()
    band_stats = tune_odds_bands()
    sport_stats = tune_sports()

    blocked_bands = [k for k, v in band_stats.items() if v["verdict"] == "BLOCKED"]
    blocked_sports = [k for k, v in sport_stats.items() if v["verdict"] == "BLOCKED"]

    summary = {
        "blacklist_count": len(blacklist),
        "whitelist_count": len(whitelist),
        "blocked_bands": blocked_bands,
        "blocked_sports": blocked_sports,
    }

    logger.info(
        f"[auto_tune] BL {len(blacklist)} 人 / WL {len(whitelist)} 人 / "
        f"除外帯 {blocked_bands} / 除外スポーツ {blocked_sports}"
    )

    # 履歴保存
    from datetime import datetime, timezone
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "band_stats": band_stats,
        "sport_stats": sport_stats,
    }
    logs = []
    if os.path.exists(TUNE_LOG_PATH):
        try:
            with open(TUNE_LOG_PATH, "r", encoding="utf-8") as f:
                logs = json.load(f)
        except Exception:
            logs = []
    logs.append(log_entry)
    # 最新50件だけ残す
    logs = logs[-50:]
    with open(TUNE_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(logs, f, indent=2, ensure_ascii=False, default=str)

    return summary


def print_tune_status() -> None:
    """現在の自動調整状況を表示"""
    band_stats = tune_odds_bands()
    sport_stats = tune_sports()

    print("\n" + "=" * 70)
    print(" 自動調整ステータス")
    print("=" * 70)

    print("\n[オッズ帯]")
    print(f"{'帯':<14}{'決着':>6}{'勝':>5}{'勝率':>8}{'P&L':>10}  判定")
    for label, s in band_stats.items():
        wr = f"{s['win_rate']*100:.1f}%" if s['decided'] else "-"
        mark = {"BLOCKED": "🚫", "GOOD": "✓", "OK": "○", "NOT_ENOUGH_DATA": "?"}[s["verdict"]]
        print(f"{label:<14}{s['decided']:>6}{s['wins']:>5}{wr:>8}{s['pnl']:>+10.2f}  {mark} {s['verdict']}")

    print("\n[スポーツ]")
    print(f"{'スポーツ':<14}{'決着':>6}{'勝':>5}{'勝率':>8}{'P&L':>10}  判定")
    for sport, s in sorted(sport_stats.items(), key=lambda x: -x[1]["pnl"]):
        wr = f"{s['win_rate']*100:.1f}%" if s['decided'] else "-"
        mark = {"BLOCKED": "🚫", "GOOD": "✓", "OK": "○", "NOT_ENOUGH_DATA": "?"}[s["verdict"]]
        print(f"{sport:<14}{s['decided']:>6}{s['wins']:>5}{wr:>8}{s['pnl']:>+10.2f}  {mark} {s['verdict']}")

    print("=" * 70 + "\n")


if __name__ == "__main__":
    run_auto_tune()
    print_tune_status()
