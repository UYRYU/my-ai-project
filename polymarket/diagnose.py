"""
Polymarket Tracker - ペーパートレード診断モジュール
どこで負けているかを特定するためのブレークダウン。
"""

import json
import os
from collections import defaultdict
from typing import Dict

from loguru import logger


PAPER_TRADES_PATH = "data/paper_trades.json"


def _load_trades() -> list:
    if not os.path.exists(PAPER_TRADES_PATH):
        return []
    with open(PAPER_TRADES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _odds_band(odds: float) -> str:
    if odds < 0.35: return "<0.35"
    if odds < 0.4: return "0.35-0.40"
    if odds < 0.5: return "0.40-0.50"
    if odds < 0.6: return "0.50-0.60"
    if odds < 0.7: return "0.60-0.70"
    if odds < 0.8: return "0.70-0.80"
    return ">=0.80"


def _detect_sport(title: str) -> str:
    if not title:
        return "OTHER"
    upper = title.upper()
    if "NBA" in upper or "WARRIORS" in upper or "LAKERS" in upper or "CELTICS" in upper:
        return "NBA"
    if "NHL" in upper or "BRUINS" in upper or "CANUCKS" in upper or "RANGERS" in upper:
        return "NHL"
    if "MLB" in upper or "YANKEES" in upper or "DODGERS" in upper or "RED SOX" in upper or "ORIOLES" in upper:
        return "MLB"
    if "COUNTER-STRIKE" in upper or "CS:" in upper or "CS2" in upper:
        return "CS2"
    if "LOL" in upper or "DOTA" in upper or "VALORANT" in upper or "ESPORTS" in upper:
        return "ESPORTS"
    if "FC" in upper or "CHAMPIONS LEAGUE" in upper or "PSG" in upper or "ARSENAL" in upper or "REAL MADRID" in upper:
        return "SOCCER"
    if "O/U" in upper or "OVER" in upper or "UNDER" in upper:
        return "O/U"
    if "OPEN" in upper or "BMW" in upper or "ATP" in upper or "WTA" in upper:
        return "TENNIS"
    if "VS" in upper or "VS." in upper:
        return "OTHER_VS"
    return "OTHER"


def _summarize(group: list) -> dict:
    closed = [t for t in group if t.get("status") == "closed"]
    wins = [t for t in closed if t.get("result") == 1]
    losses = [t for t in closed if t.get("result") == 0]
    pnl = sum(t.get("pnl", 0) for t in closed)
    return {
        "count": len(group),
        "decided": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(closed) if closed else None,
        "pnl": pnl,
        "avg_odds": sum(t.get("odds", 0) for t in group) / len(group) if group else 0,
    }


def print_diagnosis() -> None:
    trades = _load_trades()
    if not trades:
        print("ペーパートレードがありません")
        return

    # 全体
    total = _summarize(trades)
    print("\n" + "=" * 80)
    print(" ペーパートレード診断")
    print("=" * 80)
    print(f" 全体: {total['count']} 件 / 決着 {total['decided']} 件 / "
          f"勝率 {(total['win_rate'] or 0)*100:.1f}% / P&L ${total['pnl']:+.2f}")

    # オッズ帯別
    by_band = defaultdict(list)
    for t in trades:
        by_band[_odds_band(t.get("odds", 0))].append(t)

    print("\n[1] オッズ帯別")
    print("-" * 80)
    print(f"{'帯':<12}{'件':>5}{'決着':>5}{'勝':>5}{'負':>5}{'勝率':>9}{'P&L':>12}")
    for band in ["0.35-0.40", "0.40-0.50", "0.50-0.60", "0.60-0.70", "0.70-0.80", "<0.35", ">=0.80"]:
        if band not in by_band:
            continue
        s = _summarize(by_band[band])
        wr = f"{s['win_rate']*100:.1f}%" if s['win_rate'] is not None else "-"
        print(f"{band:<12}{s['count']:>5}{s['decided']:>5}{s['wins']:>5}{s['losses']:>5}{wr:>9}{s['pnl']:>+12.2f}")

    # スポーツ別
    by_sport = defaultdict(list)
    for t in trades:
        by_sport[_detect_sport(t.get("market_title", ""))].append(t)

    print("\n[2] スポーツ別")
    print("-" * 80)
    print(f"{'スポーツ':<14}{'件':>5}{'決着':>5}{'勝':>5}{'負':>5}{'勝率':>9}{'P&L':>12}")
    for sport, group in sorted(by_sport.items(), key=lambda x: -sum(t.get("pnl", 0) for t in x[1])):
        s = _summarize(group)
        wr = f"{s['win_rate']*100:.1f}%" if s['win_rate'] is not None else "-"
        print(f"{sport:<14}{s['count']:>5}{s['decided']:>5}{s['wins']:>5}{s['losses']:>5}{wr:>9}{s['pnl']:>+12.2f}")

    # outcome別
    by_outcome = defaultdict(list)
    for t in trades:
        outcome = (t.get("outcome") or "").upper()
        by_outcome[outcome].append(t)

    print("\n[3] Outcome別 (Yes/No/Over/Under/チーム名)")
    print("-" * 80)
    print(f"{'outcome':<22}{'件':>5}{'決着':>5}{'勝':>5}{'負':>5}{'勝率':>9}{'P&L':>12}")
    for outcome, group in sorted(by_outcome.items(), key=lambda x: -len(x[1]))[:15]:
        s = _summarize(group)
        wr = f"{s['win_rate']*100:.1f}%" if s['win_rate'] is not None else "-"
        name = (outcome[:20] + "..") if len(outcome) > 22 else outcome
        print(f"{name:<22}{s['count']:>5}{s['decided']:>5}{s['wins']:>5}{s['losses']:>5}{wr:>9}{s['pnl']:>+12.2f}")

    # トレーダー別 (コンセンサス時の投票者)
    # "trader"フィールドには " + " 区切りで複数名入ってる場合あり
    by_trader = defaultdict(list)
    for t in trades:
        trader_str = t.get("trader", "")
        # " + " または単独
        for tr in trader_str.split(" + "):
            tr = tr.strip()
            if tr:
                by_trader[tr].append(t)

    print("\n[4] トレーダー別 (コンセンサス参加者)")
    print("-" * 80)
    print(f"{'トレーダー':<22}{'件':>5}{'決着':>5}{'勝':>5}{'負':>5}{'勝率':>9}{'P&L':>12}")
    for trader, group in sorted(by_trader.items(), key=lambda x: -len(x[1]))[:20]:
        s = _summarize(group)
        wr = f"{s['win_rate']*100:.1f}%" if s['win_rate'] is not None else "-"
        name = (trader[:20] + "..") if len(trader) > 22 else trader
        print(f"{name:<22}{s['count']:>5}{s['decided']:>5}{s['wins']:>5}{s['losses']:>5}{wr:>9}{s['pnl']:>+12.2f}")

    # 負けトレード詳細
    losses = [t for t in trades if t.get("result") == 0]
    if losses:
        print("\n[5] 負けトレード詳細 (P&L悪い順)")
        print("-" * 80)
        for t in sorted(losses, key=lambda x: x.get("pnl", 0))[:15]:
            print(f"  ${t.get('pnl', 0):>+7.2f}  {t.get('outcome', '')[:14]:<14} "
                  f"@ {t.get('odds', 0):.3f}  {t.get('market_title', '')[:45]}")

    # 勝ちトレード
    wins = [t for t in trades if t.get("result") == 1]
    if wins:
        print("\n[6] 勝ちトレード詳細 (P&L良い順)")
        print("-" * 80)
        for t in sorted(wins, key=lambda x: -x.get("pnl", 0))[:10]:
            print(f"  ${t.get('pnl', 0):>+7.2f}  {t.get('outcome', '')[:14]:<14} "
                  f"@ {t.get('odds', 0):.3f}  {t.get('market_title', '')[:45]}")

    print("=" * 80 + "\n")


if __name__ == "__main__":
    print_diagnosis()
