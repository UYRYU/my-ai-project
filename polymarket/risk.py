"""
Polymarket Tracker - リスク管理モジュール
ポジション上限・損失制限・ベットサイズの管理

$100口座の保守的なリスク管理:
- 1回のベット: $2〜5
- 1日の最大損失: $15
- 最大同時ポジション: 5
"""

import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

from loguru import logger


# ===== リスク設定 =====
# データ分析結果 (behavior_deep.py) に基づくパラメータ
#
# 上位者のオッズ帯別ROI:
#   0.1-0.25: -19.1% (避ける)
#   0.25-0.4: +13.7%
#   0.4-0.6 : +20.2% ← 主戦場
#   0.6-0.8 : +30.1% ← 最高ROI
#
# 上位者の実サイズ: 中央値$34K (大口)
# → $100口座は比率で約1/6000 → 1ベット$5〜10が妥当

BANKROLL = 100.0           # 口座残高 ($)
BET_SIZE_MIN = 3.0         # 最小ベットサイズ ($)
BET_SIZE_DEFAULT = 5.0     # デフォルトベットサイズ ($)
BET_SIZE_MAX = 10.0        # 最大ベットサイズ ($)
MAX_DAILY_LOSS = 20.0      # 1日の最大損失 ($) - 20%まで
MAX_POSITIONS = 5           # 最大同時ポジション数

# データが示す最適オッズ帯: 0.4-0.8
# 0.1-0.25の穴狙いはROI-19%なので除外
MIN_ODDS = 0.35            # 最低オッズ
MAX_ODDS = 0.75            # 最大オッズ

# ペーパートレード記録ファイル
PAPER_TRADES_PATH = "data/paper_trades.json"
PAPER_PNL_PATH = "data/paper_pnl.json"


def _load_paper_trades() -> List[dict]:
    """ペーパートレード記録を読み込む"""
    if not os.path.exists(PAPER_TRADES_PATH):
        return []
    try:
        with open(PAPER_TRADES_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return []


def _save_paper_trades(trades: List[dict]) -> None:
    """ペーパートレード記録を保存する"""
    os.makedirs(os.path.dirname(PAPER_TRADES_PATH) or ".", exist_ok=True)
    with open(PAPER_TRADES_PATH, "w") as f:
        json.dump(trades, f, indent=2, default=str)


def get_open_positions() -> List[dict]:
    """未決着のオープンポジションを取得する"""
    trades = _load_paper_trades()
    return [t for t in trades if t.get("status") == "open"]


def get_today_pnl() -> float:
    """今日の確定損益を計算する"""
    trades = _load_paper_trades()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    daily_pnl = 0.0
    for t in trades:
        if t.get("status") == "closed" and t.get("closed_date", "").startswith(today):
            daily_pnl += t.get("pnl", 0.0)
    return daily_pnl


def get_total_pnl() -> float:
    """累計の確定損益を計算する"""
    trades = _load_paper_trades()
    return sum(t.get("pnl", 0.0) for t in trades if t.get("status") == "closed")


def can_open_position() -> tuple:
    """
    新しいポジションを開けるかチェックする。

    Returns:
        (bool, str): (開けるか, 理由)
    """
    # 同時ポジション数チェック
    open_positions = get_open_positions()
    if len(open_positions) >= MAX_POSITIONS:
        return False, f"最大ポジション数 ({MAX_POSITIONS}) に達しています"

    # 日次損失チェック
    today_pnl = get_today_pnl()
    if today_pnl <= -MAX_DAILY_LOSS:
        return False, f"本日の損失上限 (${MAX_DAILY_LOSS}) に達しています (${today_pnl:.2f})"

    return True, "OK"


def calculate_bet_size(odds: float) -> float:
    """
    オッズに応じたベットサイズを計算する。
    データ分析 (behavior_deep.py) でROIが高いオッズ帯ほど厚く張る。

    ROIデータ:
      0.4-0.6: +20.2% → 主戦場なので多めに
      0.6-0.8: +30.1% → 最高ROIなので最大
      0.35-0.4, それ以外: ディフェンシブに

    Args:
        odds: 0.0〜1.0

    Returns:
        ベットサイズ ($)
    """
    if 0.6 <= odds <= 0.75:
        return BET_SIZE_MAX       # $10 (最高ROI帯)
    elif 0.4 <= odds < 0.6:
        return BET_SIZE_DEFAULT   # $5 (主戦場)
    else:
        return BET_SIZE_MIN       # $3 (エッジ)


def record_paper_trade(
    market_id: str,
    market_title: str,
    outcome: str,
    odds: float,
    size: float,
    trader: str,
    trader_odds: float,
) -> dict:
    """
    ペーパートレードを記録する。

    Returns:
        記録したトレード情報
    """
    trades = _load_paper_trades()

    trade = {
        "id": len(trades) + 1,
        "market_id": market_id,
        "market_title": market_title,
        "outcome": outcome,
        "odds": odds,
        "size": size,
        "potential_payout": size / odds if odds > 0 else 0,
        "trader": trader,
        "trader_odds": trader_odds,
        "status": "open",        # open / closed
        "result": None,          # 1=勝ち, 0=負け
        "pnl": 0.0,
        "opened_at": datetime.now(timezone.utc).isoformat(),
        "closed_date": None,
    }

    trades.append(trade)
    _save_paper_trades(trades)

    logger.info(
        f"[PAPER] #{trade['id']} OPEN: {outcome} @ {odds:.3f} "
        f"${size:.2f} | {market_title[:50]} | follow: {trader}"
    )
    return trade


def close_paper_trade(trade_id: int, won: bool) -> Optional[dict]:
    """
    ペーパートレードを決済する。

    Args:
        trade_id: トレードID
        won: 勝ったか

    Returns:
        更新されたトレード情報
    """
    trades = _load_paper_trades()
    for t in trades:
        if t["id"] == trade_id and t["status"] == "open":
            t["status"] = "closed"
            t["result"] = 1 if won else 0
            t["closed_date"] = datetime.now(timezone.utc).isoformat()

            if won:
                # 勝ち: 配当 - 元本 = 利益
                t["pnl"] = (t["size"] / t["odds"]) - t["size"]
            else:
                # 負け: 元本を失う
                t["pnl"] = -t["size"]

            _save_paper_trades(trades)
            logger.info(
                f"[PAPER] #{t['id']} CLOSE: {'WIN' if won else 'LOSS'} "
                f"PnL=${t['pnl']:+.2f} | {t['market_title'][:50]}"
            )
            return t
    return None


def print_paper_summary() -> None:
    """ペーパートレードのサマリーを表示する"""
    trades = _load_paper_trades()
    if not trades:
        print("\nペーパートレード記録がありません\n")
        return

    open_trades = [t for t in trades if t["status"] == "open"]
    closed_trades = [t for t in trades if t["status"] == "closed"]
    wins = [t for t in closed_trades if t.get("result") == 1]
    losses = [t for t in closed_trades if t.get("result") == 0]
    total_pnl = sum(t.get("pnl", 0.0) for t in closed_trades)
    today_pnl = get_today_pnl()

    print("\n" + "=" * 60)
    print(" ペーパートレード サマリー")
    print("=" * 60)
    print(f" 総トレード数 : {len(trades)}")
    print(f" オープン     : {len(open_trades)}")
    print(f" クローズ     : {len(closed_trades)}")
    print(f" 勝ち         : {len(wins)}")
    print(f" 負け         : {len(losses)}")
    if closed_trades:
        print(f" 勝率         : {len(wins)/len(closed_trades)*100:.1f}%")
    print(f" 累計損益      : ${total_pnl:+.2f}")
    print(f" 本日損益      : ${today_pnl:+.2f}")
    print(f" 仮想残高      : ${BANKROLL + total_pnl:.2f}")

    if open_trades:
        print(f"\n--- オープンポジション ({len(open_trades)}) ---")
        for t in open_trades:
            print(
                f"  #{t['id']} {t['outcome']} @ {t['odds']:.3f} "
                f"${t['size']:.2f} | {t['market_title'][:40]}"
            )

    print("=" * 60 + "\n")
