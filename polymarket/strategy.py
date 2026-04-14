"""
Polymarket Tracker - シグナル検出モジュール
上位トレーダーの新規ベットを検知し、コピートレードのシグナルを生成する。

戦略: 低オッズ穴狙い (0.05〜0.50)
根拠: データ分析で低オッズ帯の勝率が40.4% (期待値プラス) であることを確認済み
"""

import json
import os
import time
from typing import List, Optional

import requests
from loguru import logger

import config
import risk


# 過去に検知済みのシグナルを記録するファイル
SEEN_SIGNALS_PATH = "data/seen_signals.json"


def _load_seen() -> set:
    """検知済みシグナルの一意キーを読み込む"""
    if not os.path.exists(SEEN_SIGNALS_PATH):
        return set()
    try:
        with open(SEEN_SIGNALS_PATH, "r") as f:
            return set(json.load(f))
    except Exception:
        return set()


def _save_seen(seen: set) -> None:
    """検知済みシグナルを保存する"""
    os.makedirs(os.path.dirname(SEEN_SIGNALS_PATH) or ".", exist_ok=True)
    with open(SEEN_SIGNALS_PATH, "w") as f:
        json.dump(list(seen), f)


def _make_signal_key(address: str, market_id: str, outcome: str) -> str:
    """シグナルの一意キーを作る (同じ人が同じマーケットの同じ方向に賭けたら1回だけ)"""
    return f"{address}|{market_id}|{outcome}"


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
    """
    CLOB API からマーケットの token_id を取得する。
    outcome="Yes" なら Yes の token_id、"No" なら No の token_id を返す。
    """
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

    # 完全一致しなければ最初のトークンを返す (Yes が先)
    if tokens:
        return tokens[0].get("token_id")
    return None


def _get_current_price(token_id: str) -> Optional[float]:
    """
    CLOB API でトークンの現在価格 (ミッドポイント) を取得する。
    """
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


def scan_for_signals(users: List[dict]) -> List[dict]:
    """
    上位トレーダーの最新取引をスキャンし、新しいシグナルを検出する。
    ブラックリスト (負けトレーダー) は自動で除外する。
    """
    import trader_stats

    seen = _load_seen()
    blacklist = trader_stats.load_blacklist()
    signals: List[dict] = []
    skipped_blacklist = 0

    for user in users:
        address = user["address"]
        username = user.get("username", "")

        # ブラックリストのトレーダーはスキップ
        trader_name = username or address
        if trader_name in blacklist:
            skipped_blacklist += 1
            continue

        # 最新の取引を少量取得
        try:
            params = {"user": address, "limit": 20}
            raw = _request_with_retry(config.ACTIVITY_URL, params)
        except Exception as e:
            logger.warning(f"[strategy] {username} のアクティビティ取得失敗: {e}")
            continue

        time.sleep(config.REQUEST_SLEEP)

        # レスポンス形式の正規化
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

            if not market_id or not outcome:
                continue

            try:
                price = float(price)
            except (TypeError, ValueError):
                continue

            # 戦略フィルタ: 穴狙いのみ (0.05〜0.50)
            if price < risk.MIN_ODDS or price > risk.MAX_ODDS:
                continue

            # 重複チェック
            key = _make_signal_key(address, market_id, outcome)
            if key in seen:
                continue

            # 新規シグナル!
            seen.add(key)

            signal = {
                "trader": username or address,
                "address": address,
                "market_id": market_id,
                "market_title": title,
                "outcome": outcome,
                "trader_odds": price,
                "token_id": None,  # 後で取得
            }
            signals.append(signal)
            logger.info(
                f"[SIGNAL] {username}: {outcome} @ {price:.3f} | {title[:50]}"
            )

    _save_seen(seen)
    logger.info(
        f"スキャン完了: {len(signals)} 件の新規シグナル "
        f"(ブラックリスト {skipped_blacklist} 人スキップ)"
    )
    return signals


def enrich_signals(signals: List[dict]) -> List[dict]:
    """
    シグナルに token_id と現在価格を追加する。
    """
    enriched = []
    for sig in signals:
        # token_id を取得
        token_id = _get_token_id_for_outcome(sig["market_id"], sig["outcome"])
        if not token_id:
            logger.warning(f"  token_id 取得失敗: {sig['market_title'][:40]}")
            continue

        sig["token_id"] = token_id
        time.sleep(config.REQUEST_SLEEP)

        # 現在価格を取得
        current_price = _get_current_price(token_id)
        sig["current_odds"] = current_price or sig["trader_odds"]

        enriched.append(sig)

    return enriched
