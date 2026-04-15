"""
Polymarket Tracker - シグナル検出モジュール (コンセンサス版)

戦略:
  1. オッズ 0.35〜0.75 (データが示す最適帯, ROI +20〜30%)
  2. Spread系マーケットは除外 (大負けが集中)
  3. 最後まで保有 (早期利確しない)
  4. ブラックリスト (負けトレーダー) は除外
  5. ★ コンセンサス条件: 2人以上の上位者が同じマーケット・同じ方向に
     ベットした場合のみ発火 (単独ベットは保留)
"""

import json
import os
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

import requests
from loguru import logger

import config
import risk


# ===== コンセンサス設定 =====
MIN_TRADERS_FOR_CONSENSUS = 2   # 最低何人が同じ方向に賭けたら発火するか
CONSENSUS_WINDOW_HOURS = 6      # この時間内にベットが集まればコンセンサス扱い
PENDING_CLEANUP_HOURS = 24      # これ以上古い pending は削除


# ===== 除外パターン =====
# 上位負けTop5のうち4件がSpread系だったため除外
# また、ペーパートレードで O/U (Over/Under) は全敗だったため除外
EXCLUDE_KEYWORDS = [
    "SPREAD:",
    "(-",           # ハンディキャップ表記 (-X.5)
    "(+",           # ハンディキャップ表記 (+X.5)
    "O/U ",         # Over/Under マーケット (ペーパーで全敗)
    ": O/U",
]

# outcome が OVER/UNDER のものは除外
EXCLUDE_OUTCOMES = {"OVER", "UNDER"}


def _is_excluded_market(title: str, outcome: str = "") -> bool:
    """除外すべきマーケット (Spread系 / O/U系) かチェック"""
    if not title:
        return False
    upper = title.upper()
    for kw in EXCLUDE_KEYWORDS:
        if kw in upper:
            return True
    # Outcome が OVER/UNDER なら除外
    if outcome and outcome.strip().upper() in EXCLUDE_OUTCOMES:
        return True
    return False


# ===== ファイルパス =====
PENDING_SIGNALS_PATH = "data/pending_signals.json"
FIRED_CONSENSUS_PATH = "data/fired_consensus.json"


def _load_pending() -> Dict[str, dict]:
    """
    保留中のシグナルを読み込む。
    キー = "market_id|outcome"、値 = {title, trader_votes: [{trader, odds, timestamp}], ...}
    """
    if not os.path.exists(PENDING_SIGNALS_PATH):
        return {}
    try:
        with open(PENDING_SIGNALS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_pending(pending: Dict[str, dict]) -> None:
    os.makedirs(os.path.dirname(PENDING_SIGNALS_PATH) or ".", exist_ok=True)
    with open(PENDING_SIGNALS_PATH, "w", encoding="utf-8") as f:
        json.dump(pending, f, ensure_ascii=False, indent=2)


def _load_fired() -> set:
    """既に発火済みのコンセンサスキーを読み込む"""
    if not os.path.exists(FIRED_CONSENSUS_PATH):
        return set()
    try:
        with open(FIRED_CONSENSUS_PATH, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def _save_fired(fired: set) -> None:
    os.makedirs(os.path.dirname(FIRED_CONSENSUS_PATH) or ".", exist_ok=True)
    with open(FIRED_CONSENSUS_PATH, "w", encoding="utf-8") as f:
        json.dump(list(fired), f)


def _make_consensus_key(market_id: str, outcome: str) -> str:
    """コンセンサス識別キー (市場とoutcomeが同じなら同じコンセンサス)"""
    return f"{market_id}|{outcome}"


def _request_with_retry(url: str, params: dict) -> list:
    """APIリクエストをリトライ付きで実行"""
    last_exc = None
    for attempt in range(1, config.RETRY_COUNT + 1):
        try:
            response = requests.get(url, params=params, timeout=config.REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            last_exc = e
            if attempt < config.RETRY_COUNT:
                time.sleep(config.RETRY_INTERVAL)
    raise RuntimeError(f"リクエスト失敗: {last_exc}")


def _get_token_id_for_outcome(market_id: str, outcome: str) -> Optional[str]:
    """CLOB API からマーケットの token_id を取得"""
    try:
        data = _request_with_retry(f"{config.CLOB_URL}/{market_id}", {})
    except Exception as e:
        logger.warning(f"CLOB マーケット取得失敗: {e}")
        return None

    if not isinstance(data, dict):
        return None

    tokens = data.get("tokens") or []
    target = outcome.strip().upper()
    for token in tokens:
        if (token.get("outcome") or "").strip().upper() == target:
            return token.get("token_id")

    if tokens:
        return tokens[0].get("token_id")
    return None


def _get_current_price(token_id: str) -> Optional[float]:
    """CLOB API でトークンの現在価格 (ミッドポイント) を取得"""
    try:
        data = _request_with_retry(
            f"https://clob.polymarket.com/midpoint",
            {"token_id": token_id},
        )
        if isinstance(data, dict) and "mid" in data:
            return float(data["mid"])
    except Exception:
        pass
    return None


def _cleanup_old_pending(pending: Dict[str, dict]) -> Dict[str, dict]:
    """古い pending signal を削除する"""
    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - PENDING_CLEANUP_HOURS * 3600

    cleaned = {}
    removed = 0
    for key, entry in pending.items():
        # 最新の投票時刻でジャッジ
        votes = entry.get("trader_votes", [])
        if not votes:
            removed += 1
            continue
        latest_ts = max((v.get("timestamp", 0) for v in votes), default=0)
        if latest_ts > cutoff:
            cleaned[key] = entry
        else:
            removed += 1
    if removed:
        logger.info(f"  古い pending シグナル {removed} 件を削除")
    return cleaned


def scan_for_signals(users: List[dict]) -> List[dict]:
    """
    上位トレーダーの最新取引をスキャンし、コンセンサスが成立したシグナルを返す。

    フロー:
      1. 各上位者の最新ベットを取得
      2. 条件 (オッズ範囲/Spread除外/ブラックリスト) でフィルタ
      3. pending_signals に投票として記録
      4. 同じ (market_id, outcome) に MIN_TRADERS_FOR_CONSENSUS 人以上の投票があれば発火
      5. 既に発火済みは重複発火しない

    Returns:
        コンセンサス成立シグナルのリスト
    """
    import trader_stats

    pending = _load_pending()
    pending = _cleanup_old_pending(pending)
    fired = _load_fired()
    blacklist = trader_stats.load_blacklist()
    whitelist = trader_stats.load_whitelist()

    # 即時発火したシグナル (ホワイトリスト単独ベット)
    immediate_signals: List[dict] = []

    skipped_blacklist = 0
    new_votes = 0
    now_ts = datetime.now(timezone.utc).timestamp()
    window_cutoff = now_ts - CONSENSUS_WINDOW_HOURS * 3600

    # --- ステップ1: 各上位者からベットを収集して pending に投票 ---
    for user in users:
        address = user["address"]
        username = user.get("username", "")

        # ブラックリストのトレーダーはスキップ
        trader_name = username or address
        if trader_name in blacklist:
            skipped_blacklist += 1
            continue

        try:
            params = {"user": address, "limit": 20}
            raw = _request_with_retry(config.ACTIVITY_URL, params)
        except Exception as e:
            logger.warning(f"[strategy] {username} のアクティビティ取得失敗: {e}")
            continue

        time.sleep(config.REQUEST_SLEEP)

        if isinstance(raw, dict):
            activities = raw.get("data") or raw.get("activities") or []
        else:
            activities = raw if isinstance(raw, list) else []

        for act in activities:
            market_id = (
                act.get("marketId")
                or act.get("conditionId")
                or act.get("market")
                or ""
            )
            outcome = act.get("outcome") or act.get("side") or ""
            price = act.get("price") or act.get("avgPrice") or 0
            title = (
                act.get("title")
                or act.get("eventTitle")
                or act.get("marketTitle")
                or act.get("question")
                or ""
            )

            # 取引タイムスタンプ (ミリ秒の場合もあるので正規化)
            ts_raw = act.get("timestamp") or act.get("createdAt") or 0
            try:
                ts = float(ts_raw)
                if ts > 1e12:
                    ts = ts / 1000.0
                ts = int(ts)
            except (TypeError, ValueError):
                ts = 0

            if not market_id or not outcome:
                continue

            try:
                price = float(price)
            except (TypeError, ValueError):
                continue

            # フィルタ適用
            if price < risk.MIN_ODDS or price > risk.MAX_ODDS:
                continue
            if _is_excluded_market(title, outcome):
                continue

            key = _make_consensus_key(market_id, outcome)

            # 既に発火済みならスキップ
            if key in fired:
                continue

            # pending に投票追加 (同じトレーダーの同じマーケットは1票まで)
            entry = pending.get(key) or {
                "market_id": market_id,
                "outcome": outcome,
                "title": title,
                "trader_votes": [],
            }
            existing_traders = {v["trader"] for v in entry["trader_votes"]}
            if trader_name in existing_traders:
                continue  # 同じ人の2票目は無視

            entry["trader_votes"].append({
                "trader": trader_name,
                "odds": price,
                "timestamp": ts or int(now_ts),
            })
            entry["title"] = title or entry.get("title", "")
            pending[key] = entry
            new_votes += 1

            # ★ ホワイトリストのトレーダーは単独でも即発火
            if trader_name in whitelist and key not in fired:
                logger.info(
                    f"[WHITELIST即発火] {trader_name}: {outcome} @ {price:.3f} | {title[:50]}"
                )
                immediate_signals.append({
                    "trader": trader_name,
                    "traders": [trader_name],
                    "vote_count": 1,
                    "fire_reason": "WHITELIST",
                    "market_id": market_id,
                    "market_title": title,
                    "outcome": outcome,
                    "trader_odds": price,
                    "token_id": None,
                })
                fired.add(key)
                # pending からも削除
                if key in pending:
                    del pending[key]

    # --- ステップ2: コンセンサスが成立したシグナルを抽出 ---
    signals = list(immediate_signals)  # ホワイトリスト即発火分を先に入れる
    for key, entry in list(pending.items()):
        # 時間窓内の投票のみカウント
        recent_votes = [
            v for v in entry["trader_votes"]
            if v.get("timestamp", 0) >= window_cutoff
        ]

        if len(recent_votes) >= MIN_TRADERS_FOR_CONSENSUS:
            # 発火!
            avg_odds = sum(v["odds"] for v in recent_votes) / len(recent_votes)
            traders = [v["trader"] for v in recent_votes]

            signal = {
                "trader": " + ".join(traders[:3]),  # 表示用
                "traders": traders,
                "vote_count": len(recent_votes),
                "market_id": entry["market_id"],
                "market_title": entry["title"],
                "outcome": entry["outcome"],
                "trader_odds": avg_odds,  # 投票の平均オッズ
                "token_id": None,
            }
            signals.append(signal)
            fired.add(key)

            logger.info(
                f"[CONSENSUS {len(recent_votes)}人] {entry['outcome']} "
                f"@ {avg_odds:.3f} | {entry['title'][:50]} | {', '.join(traders)}"
            )
            # 発火したので pending から削除
            del pending[key]

    # 状態を保存
    _save_pending(pending)
    _save_fired(fired)

    # --- サマリー ---
    total_pending_markets = len(pending)
    pending_single = sum(
        1 for e in pending.values() if len(e["trader_votes"]) == 1
    )
    pending_near = sum(
        1 for e in pending.values()
        if len(e["trader_votes"]) >= MIN_TRADERS_FOR_CONSENSUS - 1
        and len(e["trader_votes"]) < MIN_TRADERS_FOR_CONSENSUS
    )

    logger.info(
        f"スキャン完了: 新規投票 {new_votes} 件 | "
        f"即発火 {len(immediate_signals)} 件 (WL) | "
        f"合計発火 {len(signals)} 件 | "
        f"保留中 {total_pending_markets} 件 (単独 {pending_single}) | "
        f"BL除外 {skipped_blacklist} 人 | "
        f"WL {len(whitelist)} 人"
    )
    return signals


def enrich_signals(signals: List[dict]) -> List[dict]:
    """シグナルに token_id と現在価格を追加"""
    enriched = []
    for sig in signals:
        token_id = _get_token_id_for_outcome(sig["market_id"], sig["outcome"])
        if not token_id:
            logger.warning(f"  token_id 取得失敗: {sig['market_title'][:40]}")
            continue

        sig["token_id"] = token_id
        time.sleep(config.REQUEST_SLEEP)

        current_price = _get_current_price(token_id)
        sig["current_odds"] = current_price or sig["trader_odds"]

        enriched.append(sig)

    return enriched


def print_pending_signals() -> None:
    """保留中のシグナルをコンソール表示 (デバッグ用)"""
    pending = _load_pending()
    if not pending:
        print("\n保留中のシグナルはありません\n")
        return

    print("\n" + "=" * 80)
    print(f" 保留中のシグナル ({len(pending)} マーケット)")
    print(f" コンセンサス条件: {MIN_TRADERS_FOR_CONSENSUS} 人以上の投票で発火")
    print("=" * 80)

    # 投票数が多い順
    sorted_items = sorted(
        pending.items(),
        key=lambda x: len(x[1]["trader_votes"]),
        reverse=True,
    )

    for key, entry in sorted_items:
        votes = entry["trader_votes"]
        status = "🔥READY" if len(votes) >= MIN_TRADERS_FOR_CONSENSUS else f"待機 ({len(votes)}/{MIN_TRADERS_FOR_CONSENSUS})"
        avg_odds = sum(v["odds"] for v in votes) / len(votes) if votes else 0
        print(
            f"\n {status}  {entry['outcome']} @ {avg_odds:.3f}  "
            f"| {entry['title'][:55]}"
        )
        for v in votes:
            print(f"    - {v['trader']} @ {v['odds']:.3f}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    print_pending_signals()
