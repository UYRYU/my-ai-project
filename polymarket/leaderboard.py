"""
Polymarket Tracker - リーダーボード取得モジュール
上位トレーダーのアドレス・ユーザー名・利益を取得する
"""

import json
import time
from typing import List

import requests
from loguru import logger

import config


def _request_with_retry(url: str, params: dict) -> dict:
    """
    APIリクエストをリトライ付きで実行するヘルパー関数
    最大 config.RETRY_COUNT 回までリトライする
    """
    last_exc = None
    for attempt in range(1, config.RETRY_COUNT + 1):
        try:
            response = requests.get(
                url,
                params=params,
                timeout=config.REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            last_exc = e
            logger.warning(
                f"[leaderboard] リクエスト失敗 (attempt {attempt}/{config.RETRY_COUNT}): {e}"
            )
            # 最後の試行でなければ少し待つ
            if attempt < config.RETRY_COUNT:
                time.sleep(config.RETRY_INTERVAL)
    # 全てのリトライが失敗
    raise RuntimeError(f"リーダーボード取得に失敗しました: {last_exc}")


def get_leaderboard() -> List[dict]:
    """
    Polymarket のリーダーボードを取得し、上位 TOP_N 人の
    address, username, profit を含むリストを返す。

    Returns:
        List[dict]: 例 [{"address": "0x...", "username": "alice", "profit": 12345.6}, ...]
    """
    logger.info("リーダーボードを取得中...")

    params = {
        "limit": 20,       # 余裕を持って20件取得
        "window": "all",   # 全期間
    }

    try:
        data = _request_with_retry(config.LEADERBOARD_URL, params)
    except Exception as e:
        logger.error(f"リーダーボード取得エラー: {e}")
        return []

    # レスポンス形式によって取り出し方を変える
    # Polymarket API は通常リストをそのまま返すが、{"data": [...]} の場合もある
    if isinstance(data, dict):
        records = data.get("data") or data.get("leaderboard") or []
    else:
        records = data

    if not isinstance(records, list):
        logger.error(f"予期しないレスポンス形式: {type(records)}")
        return []

    # 上位 TOP_N 人を抽出
    top_users = []
    for item in records[: config.TOP_N]:
        # APIのフィールド名の揺れに対応
        address = (
            item.get("proxyWallet")
            or item.get("address")
            or item.get("wallet")
            or ""
        )
        username = (
            item.get("name")
            or item.get("username")
            or item.get("displayName")
            or ""
        )
        profit = (
            item.get("profit")
            or item.get("pnl")
            or item.get("totalPnl")
            or 0
        )

        if not address:
            continue

        top_users.append({
            "address": address,
            "username": username,
            "profit": float(profit) if profit else 0.0,
        })

    logger.info(f"上位 {len(top_users)} 人のトレーダーを取得しました")

    # leaderboard.json に保存
    try:
        with open(config.LEADERBOARD_PATH, "w", encoding="utf-8") as f:
            json.dump(top_users, f, ensure_ascii=False, indent=2)
        logger.info(f"リーダーボードを {config.LEADERBOARD_PATH} に保存しました")
    except Exception as e:
        logger.error(f"リーダーボード保存エラー: {e}")

    # レート制限対策
    time.sleep(config.REQUEST_SLEEP)

    return top_users


if __name__ == "__main__":
    # 単体実行時はリーダーボードを表示
    users = get_leaderboard()
    for i, u in enumerate(users, 1):
        print(f"{i:2d}. {u['username']:20s} {u['address']}  profit=${u['profit']:,.2f}")
