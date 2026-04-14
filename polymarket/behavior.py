"""
Polymarket Tracker - 上位者の行動パターン分析モジュール

日次/週次/月次の上位PNL者を抽出し、彼らの全取引履歴から:
- エントリー時のオッズ
- 早期利確 (SELL) したか / 保有し続けたか
- 保有時間
- 単発 / 分割ベット
を集計して、戦略に落とし込むための知見を抽出する。

使い方:
    python main.py --behavior

出力:
    data/behavior_analysis.json  (トレーダー別の詳細)
    標準出力に集計レポート
"""

import json
import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional

import requests
from loguru import logger

import config
from leaderboard import get_leaderboard


# 抽出する人数 (各ウィンドウ × PNL)
TOP_N_PER_WINDOW = 3

# 対象ウィンドウ
WINDOWS = ["DAY", "WEEK", "MONTH"]

# 取得する取引数上限
ACTIVITY_LIMIT = 500

# 保存先
BEHAVIOR_OUTPUT_PATH = "data/behavior_analysis.json"


def _request_with_retry(url: str, params: dict) -> list:
    """APIリクエスト (リトライあり)"""
    last_exc = None
    for attempt in range(1, config.RETRY_COUNT + 1):
        try:
            r = requests.get(url, params=params, timeout=config.REQUEST_TIMEOUT)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_exc = e
            if attempt < config.RETRY_COUNT:
                time.sleep(config.RETRY_INTERVAL)
    raise RuntimeError(f"失敗: {last_exc}")


def get_top_traders() -> List[dict]:
    """日次/週次/月次のPNL上位3人ずつを重複除いて取得"""
    seen = {}
    for window in WINDOWS:
        users = get_leaderboard(window=window, board_type="PNL", save=True)
        for u in users[:TOP_N_PER_WINDOW]:
            addr = u["address"]
            if addr not in seen:
                seen[addr] = dict(u)
                seen[addr]["windows"] = [window]
            else:
                seen[addr]["windows"].append(window)

    traders = list(seen.values())
    logger.info(f"対象トレーダー: {len(traders)} 人")
    for t in traders:
        logger.info(f"  {t.get('username', '')[:20]:<20} windows={t['windows']} PnL=${t.get('profit', 0):,.0f}")
    return traders


def fetch_trader_activities(address: str) -> List[dict]:
    """トレーダーの全取引履歴を取得"""
    try:
        raw = _request_with_retry(
            config.ACTIVITY_URL,
            {"user": address, "limit": ACTIVITY_LIMIT},
        )
    except Exception as e:
        logger.error(f"アクティビティ取得失敗 [{address}]: {e}")
        return []

    time.sleep(config.REQUEST_SLEEP)

    if isinstance(raw, dict):
        activities = raw.get("data") or raw.get("activities") or []
    elif isinstance(raw, list):
        activities = raw
    else:
        activities = []

    return activities


def _get_market_resolution(condition_id: str) -> Optional[dict]:
    """
    CLOBマーケット情報 (決着済みかどうか & winner) を取得
    """
    try:
        r = requests.get(f"{config.CLOB_URL}/{condition_id}", timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        if not isinstance(data, dict):
            return None

        if not data.get("closed"):
            return {"resolved": False, "winner_outcome": None}

        tokens = data.get("tokens") or []
        for t in tokens:
            if t.get("winner"):
                return {
                    "resolved": True,
                    "winner_outcome": (t.get("outcome") or "").strip().upper(),
                }
        return {"resolved": False, "winner_outcome": None}
    except Exception:
        return None


def analyze_trader(address: str, username: str) -> dict:
    """
    1人のトレーダーの行動を分析する。

    Returns:
        {
            "address": ..., "username": ...,
            "total_markets": N,
            "held_to_end": N,       # 最後まで保有したマーケット数
            "early_exit": N,        # SELLで利確/損切りしたマーケット数
            "scaled_in": N,         # 複数回に分けてBUYしたマーケット数
            "avg_entry_odds": 0.xx,
            "avg_hold_hours": N,
            "held_win_rate": 0.xx,  # 保有派の勝率
            "markets": [...]        # マーケット別の詳細
        }
    """
    activities = fetch_trader_activities(address)
    logger.info(f"[{username[:20]}] 取引 {len(activities)} 件取得")

    # マーケットごとに BUY / SELL を集計
    by_market: Dict[str, Dict] = defaultdict(lambda: {
        "title": "",
        "outcome": "",
        "buys": [],    # [{price, size, timestamp}]
        "sells": [],   # 同上
    })

    for act in activities:
        # TRADE 系のみ
        act_type = (act.get("type") or "").upper()
        if act_type and act_type not in ("TRADE", "BUY", "SELL"):
            continue

        market_id = (
            act.get("conditionId")
            or act.get("marketId")
            or act.get("market")
            or ""
        )
        if not market_id:
            continue

        side = (act.get("side") or "").upper()
        if side not in ("BUY", "SELL"):
            # side が無い場合、type を使う
            if act_type == "BUY":
                side = "BUY"
            elif act_type == "SELL":
                side = "SELL"
            else:
                continue

        outcome = act.get("outcome") or ""
        title = (
            act.get("title")
            or act.get("eventTitle")
            or act.get("marketTitle")
            or act.get("question")
            or ""
        )

        try:
            price = float(act.get("price") or act.get("avgPrice") or 0)
        except (TypeError, ValueError):
            continue
        try:
            size = float(act.get("size") or act.get("usdcSize") or act.get("amount") or 0)
        except (TypeError, ValueError):
            size = 0
        try:
            ts = int(float(act.get("timestamp") or act.get("createdAt") or 0))
        except (TypeError, ValueError):
            ts = 0

        if price <= 0 or size <= 0:
            continue

        m = by_market[market_id]
        if not m["title"]:
            m["title"] = title
            m["outcome"] = outcome

        entry = {"price": price, "size": size, "timestamp": ts}
        if side == "BUY":
            m["buys"].append(entry)
        else:
            m["sells"].append(entry)

    # マーケット別に分析
    markets_analysis = []
    held_to_end = 0
    early_exit = 0
    scaled_in = 0
    entry_odds_list = []
    hold_hours_list = []
    held_wins = 0
    held_decided = 0

    for mid, m in by_market.items():
        if not m["buys"]:
            continue  # BUYが無いのは無視 (単なるREDEEMなど)

        # エントリー情報 (最初のBUY or 加重平均)
        first_buy_ts = min(b["timestamp"] for b in m["buys"])
        total_buy_size = sum(b["size"] for b in m["buys"])
        avg_entry_price = (
            sum(b["price"] * b["size"] for b in m["buys"]) / total_buy_size
            if total_buy_size > 0 else 0
        )

        # 分割ベットか
        is_scaled = len(m["buys"]) > 1
        if is_scaled:
            scaled_in += 1

        entry_odds_list.append(avg_entry_price)

        # 保有 or 早期利確
        has_sold = len(m["sells"]) > 0
        total_sell_size = sum(s["size"] for s in m["sells"])
        net_holding = total_buy_size - total_sell_size

        if has_sold and total_sell_size >= total_buy_size * 0.9:
            # 90%以上売却 = 早期利確/損切り
            early_exit += 1
            exit_type = "EARLY_EXIT"
            last_sell_ts = max(s["timestamp"] for s in m["sells"])
            avg_exit_price = (
                sum(s["price"] * s["size"] for s in m["sells"]) / total_sell_size
                if total_sell_size > 0 else 0
            )
            hold_seconds = last_sell_ts - first_buy_ts
            realized_pnl = (avg_exit_price - avg_entry_price) * total_sell_size
        else:
            # 保有継続 (決着待ち or 決着済)
            held_to_end += 1
            exit_type = "HELD"
            avg_exit_price = None
            # 決着情報を取得
            resolution = _get_market_resolution(mid)
            time.sleep(0.3)  # レート制限
            if resolution and resolution["resolved"]:
                held_decided += 1
                trader_outcome = (m["outcome"] or "").strip().upper()
                if trader_outcome == resolution["winner_outcome"]:
                    held_wins += 1
                    realized_pnl = (1 - avg_entry_price) * net_holding
                else:
                    realized_pnl = -avg_entry_price * net_holding
                hold_seconds = 0  # 決着済
            else:
                realized_pnl = 0  # 未決着
                hold_seconds = 0

        if exit_type == "EARLY_EXIT" and hold_seconds > 0:
            hold_hours_list.append(hold_seconds / 3600)

        markets_analysis.append({
            "market_id": mid,
            "title": m["title"][:60],
            "outcome": m["outcome"],
            "entry_price": round(avg_entry_price, 4),
            "exit_price": round(avg_exit_price, 4) if avg_exit_price else None,
            "buy_count": len(m["buys"]),
            "sell_count": len(m["sells"]),
            "buy_size": round(total_buy_size, 2),
            "sell_size": round(total_sell_size, 2),
            "scaled_in": is_scaled,
            "exit_type": exit_type,
            "hold_hours": round((
                (max(s["timestamp"] for s in m["sells"]) - first_buy_ts) / 3600
            ), 1) if has_sold else None,
            "realized_pnl": round(realized_pnl, 2),
        })

    total_markets = len(markets_analysis)
    if total_markets == 0:
        return {
            "address": address,
            "username": username,
            "total_markets": 0,
            "markets": [],
        }

    return {
        "address": address,
        "username": username,
        "total_markets": total_markets,
        "held_to_end": held_to_end,
        "early_exit": early_exit,
        "scaled_in": scaled_in,
        "hold_ratio": round(held_to_end / total_markets, 3),
        "exit_ratio": round(early_exit / total_markets, 3),
        "scale_ratio": round(scaled_in / total_markets, 3),
        "avg_entry_odds": round(sum(entry_odds_list) / len(entry_odds_list), 4) if entry_odds_list else 0,
        "avg_hold_hours": round(sum(hold_hours_list) / len(hold_hours_list), 1) if hold_hours_list else 0,
        "held_win_rate": round(held_wins / held_decided, 3) if held_decided > 0 else None,
        "held_decided": held_decided,
        "markets": markets_analysis,
    }


def print_report(analyses: List[dict]) -> None:
    """分析結果を見やすく表示"""
    print("\n" + "=" * 80)
    print(" 上位者の行動パターン分析")
    print("=" * 80)

    for a in analyses:
        if a["total_markets"] == 0:
            continue
        name = a.get("username", "")[:20] or "(no name)"
        print(f"\n━━ {name} ({a['total_markets']} マーケット) ━━")
        print(f"  保有派比率    : {a['hold_ratio']*100:.1f}%  ({a['held_to_end']} 件最後まで保有)")
        print(f"  利確派比率    : {a['exit_ratio']*100:.1f}%  ({a['early_exit']} 件早期売却)")
        print(f"  分割ベット    : {a['scale_ratio']*100:.1f}%  ({a['scaled_in']} 件)")
        print(f"  平均エントリー: {a['avg_entry_odds']:.3f}")
        if a["avg_hold_hours"] > 0:
            print(f"  平均保有時間  : {a['avg_hold_hours']:.1f} 時間 (利確派のみ)")
        if a["held_win_rate"] is not None:
            print(f"  保有派勝率    : {a['held_win_rate']*100:.1f}% ({a['held_decided']} 件決着)")

    # 全体集計
    all_markets = [m for a in analyses for m in a["markets"]]
    if not all_markets:
        print("\n(分析できるマーケットがありません)\n")
        return

    total = len(all_markets)
    held = sum(1 for m in all_markets if m["exit_type"] == "HELD")
    exited = sum(1 for m in all_markets if m["exit_type"] == "EARLY_EXIT")
    scaled = sum(1 for m in all_markets if m["scaled_in"])
    entry_odds = [m["entry_price"] for m in all_markets if m["entry_price"] > 0]
    exit_hold = [m["hold_hours"] for m in all_markets if m["hold_hours"]]

    print("\n" + "=" * 80)
    print(" 全体集計 (戦略の根拠)")
    print("=" * 80)
    print(f" 総マーケット数     : {total}")
    print(f" 最後まで保有       : {held} ({held/total*100:.1f}%)")
    print(f" 早期利確/損切り    : {exited} ({exited/total*100:.1f}%)")
    print(f" 分割ベット         : {scaled} ({scaled/total*100:.1f}%)")
    if entry_odds:
        print(f" 平均エントリーオッズ: {sum(entry_odds)/len(entry_odds):.3f}")
        print(f"   最低: {min(entry_odds):.3f} / 最高: {max(entry_odds):.3f}")
    if exit_hold:
        print(f" 利確派の平均保有  : {sum(exit_hold)/len(exit_hold):.1f} 時間")

    # 戦略推奨
    print("\n" + "=" * 80)
    print(" 戦略の示唆")
    print("=" * 80)
    hold_pct = held / total * 100
    if hold_pct > 60:
        print(f" → 上位者は主に【保有派】({hold_pct:.0f}%): 最後まで保有して決着を待つ戦略")
    elif hold_pct < 40:
        print(f" → 上位者は主に【利確派】({exited/total*100:.0f}%): オッズ上昇で早期売却する戦略")
    else:
        print(f" → 混在型 ({hold_pct:.0f}%保有 / {exited/total*100:.0f}%利確): マーケット特性で使い分け")

    if scaled / total > 0.3:
        print(f" → 分割ベット率{scaled/total*100:.0f}%: ポジション積み増しをしている")

    if entry_odds:
        avg_e = sum(entry_odds) / len(entry_odds)
        if avg_e < 0.4:
            print(f" → 平均エントリー {avg_e:.3f}: 穴狙い傾向")
        elif avg_e > 0.6:
            print(f" → 平均エントリー {avg_e:.3f}: 本命狙い傾向")
        else:
            print(f" → 平均エントリー {avg_e:.3f}: 中オッズ中心")

    print("=" * 80 + "\n")


def run_analysis() -> None:
    """分析のエントリーポイント"""
    logger.info("=" * 50)
    logger.info("上位者の行動パターン分析を開始")
    logger.info("=" * 50)

    traders = get_top_traders()
    if not traders:
        logger.error("対象トレーダーが取得できませんでした")
        return

    analyses = []
    for i, t in enumerate(traders, 1):
        logger.info(f"[{i}/{len(traders)}] {t.get('username', '')[:20]} を分析中...")
        analysis = analyze_trader(t["address"], t.get("username", ""))
        analysis["source_windows"] = t.get("windows", [])
        analysis["leaderboard_pnl"] = t.get("profit", 0)
        analyses.append(analysis)

    # 保存
    os.makedirs(os.path.dirname(BEHAVIOR_OUTPUT_PATH) or ".", exist_ok=True)
    with open(BEHAVIOR_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(analyses, f, indent=2, ensure_ascii=False, default=str)
    logger.info(f"保存: {BEHAVIOR_OUTPUT_PATH}")

    # レポート出力
    print_report(analyses)


if __name__ == "__main__":
    run_analysis()
