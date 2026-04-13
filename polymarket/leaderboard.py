"""
Polymarket Tracker - リーダーボード取得モジュール
上位トレーダーのアドレス・ユーザー名・利益/取引量を取得する。
Polymarket v1 API: /v1/leaderboard
パラメータ: timePeriod (DAY/WEEK/MONTH/ALL), orderBy (PNL/VOL), category, limit, offset
レスポンスフィールド: rank, proxyWallet, username, vol, pnl, profileImage, xUsername, verified
"""

import json
import os
import time
from typing import Dict, List, Optional

import requests
from loguru import logger

import config


def _request_with_retry(url: str, params: dict) -> dict:
    """
    APIリクエストをリトライ付きで実行するヘルパー関数。
    最大 config.RETRY_COUNT 回までリトライする。
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
            if attempt < config.RETRY_COUNT:
                time.sleep(config.RETRY_INTERVAL)
    raise RuntimeError(f"リーダーボード取得に失敗しました: {last_exc}")


def _extract_records(data) -> list:
    """
    レスポンスJSONから実際のレコード配列を取り出す。
    v1 API はリストを直接返すが、dict の場合にも対応。
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("data", "leaderboard", "results", "items"):
            if key in data and isinstance(data[key], list):
                return data[key]
    return []


def _parse_user(item: dict) -> Optional[dict]:
    """
    v1 API レスポンスの1レコードから統一フォーマットに変換する。

    v1 API の既知フィールド:
        rank, proxyWallet, username, vol, pnl, profileImage, xUsername, verified

    Returns:
        {"address": str, "username": str, "profit": float, "volume": float, "rank": int} or None
    """
    # アドレス取得 (v1 は proxyWallet を返す)
    address = (
        item.get("proxyWallet")
        or item.get("address")
        or item.get("wallet")
        or item.get("user")
        or ""
    )
    if not address:
        return None

    # ユーザー名
    username = (
        item.get("username")
        or item.get("name")
        or item.get("displayName")
        or item.get("pseudonym")
        or ""
    )

    # PnL (利益)
    pnl_raw = item.get("pnl") or item.get("profit") or item.get("totalPnl") or 0
    # Volume (取引量)
    vol_raw = item.get("vol") or item.get("volume") or item.get("totalVolume") or 0
    # Rank
    rank_raw = item.get("rank") or 0

    try:
        profit = float(pnl_raw)
    except (TypeError, ValueError):
        profit = 0.0
    try:
        volume = float(vol_raw)
    except (TypeError, ValueError):
        volume = 0.0
    try:
        rank = int(rank_raw)
    except (TypeError, ValueError):
        rank = 0

    return {
        "address": address,
        "username": username,
        "profit": profit,
        "volume": volume,
        "rank": rank,
    }


def get_leaderboard(
    window: str = "ALL",
    board_type: str = "PNL",
    limit: Optional[int] = None,
    save: bool = True,
) -> List[dict]:
    """
    Polymarket v1 リーダーボードを取得する。

    Args:
        window: "DAY" / "WEEK" / "MONTH" / "ALL"
        board_type: "PNL" (利益順) or "VOL" (取引量順)
        limit: 取得数。省略時は TOP_N * 2
        save: True なら data/leaderboards/{type}_{window}.json に保存

    Returns:
        List[dict]: 上位 TOP_N 人の {address, username, profit, volume, rank}
    """
    label = config.WINDOW_LABELS.get(window, window)
    logger.info(f"リーダーボード取得中... timePeriod={window}({label}) orderBy={board_type}")

    fetch_limit = limit if limit is not None else max(config.TOP_N * 2, 25)

    # Polymarket v1 API パラメータ
    params = {
        "timePeriod": window,       # DAY / WEEK / MONTH / ALL
        "orderBy": board_type,      # PNL / VOL
        "category": config.LEADERBOARD_CATEGORY,  # SPORTS
        "limit": fetch_limit,
        "offset": 0,
    }

    try:
        data = _request_with_retry(config.LEADERBOARD_URL, params)
    except Exception as e:
        logger.error(f"リーダーボード取得エラー [timePeriod={window}, orderBy={board_type}]: {e}")
        return []

    records = _extract_records(data)
    if not records:
        logger.warning(f"レコードが空 or 予期しない形式: {type(data)}")
        # デバッグ用にレスポンス冒頭を表示
        logger.debug(f"レスポンス冒頭: {str(data)[:500]}")
        return []

    # 上位 TOP_N 人を抽出
    top_users: List[dict] = []
    for item in records[: config.TOP_N]:
        parsed = _parse_user(item)
        if parsed:
            top_users.append(parsed)

    logger.info(f"  → {len(top_users)} 人を取得 ({window}/{board_type})")

    # 保存
    if save and top_users:
        os.makedirs(config.LEADERBOARD_DIR, exist_ok=True)
        out_path = os.path.join(
            config.LEADERBOARD_DIR,
            f"{board_type}_{window}.json",
        )
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(top_users, f, ensure_ascii=False, indent=2)
            logger.info(f"  → 保存: {out_path}")
        except Exception as e:
            logger.error(f"保存エラー: {e}")

        # 互換性: window=ALL & type=PNL のときは leaderboard.json にも保存
        if window == "ALL" and board_type == "PNL":
            try:
                with open(config.LEADERBOARD_PATH, "w", encoding="utf-8") as f:
                    json.dump(top_users, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"leaderboard.json 保存エラー: {e}")

    # レート制限対策
    time.sleep(config.REQUEST_SLEEP)
    return top_users


def get_all_leaderboards() -> Dict[str, List[dict]]:
    """
    全ウィンドウ × 全種別のリーダーボードを取得する。
    戻り値のキーは "{type}_{window}" (例: "PNL_DAY")。
    """
    results: Dict[str, List[dict]] = {}
    for board_type in config.LEADERBOARD_TYPES:
        for window in config.WINDOWS:
            key = f"{board_type}_{window}"
            try:
                results[key] = get_leaderboard(
                    window=window,
                    board_type=board_type,
                    save=True,
                )
            except Exception as e:
                logger.error(f"[{key}] 取得失敗: {e}")
                results[key] = []
    return results


def get_tracked_traders() -> List[dict]:
    """
    TRACK_WINDOWS × TRACK_TYPES で指定された範囲の上位者を全て集め、
    アドレスで重複排除して返す。tracker.py から呼ばれる想定。

    Returns:
        List[dict]: 追跡対象のユーザーリスト (重複なし)
    """
    seen: Dict[str, dict] = {}

    for board_type in config.TRACK_TYPES:
        for window in config.TRACK_WINDOWS:
            users = get_leaderboard(
                window=window,
                board_type=board_type,
                save=True,
            )
            source_tag = f"{board_type}_{window}"
            for u in users:
                addr = u["address"]
                if addr not in seen:
                    seen[addr] = dict(u)
                    seen[addr]["sources"] = [source_tag]
                else:
                    seen[addr]["sources"].append(source_tag)
                    if u.get("profit", 0) > seen[addr].get("profit", 0):
                        seen[addr]["profit"] = u["profit"]
                    if u.get("volume", 0) > seen[addr].get("volume", 0):
                        seen[addr]["volume"] = u["volume"]

    tracked = list(seen.values())
    logger.info(
        f"追跡対象トレーダー: {len(tracked)} 人 "
        f"(windows={config.TRACK_WINDOWS}, types={config.TRACK_TYPES})"
    )
    return tracked


def print_leaderboard(users: List[dict], title: str = "") -> None:
    """リーダーボードを整形してコンソール表示するヘルパー"""
    if title:
        print(f"\n===== {title} =====")
    if not users:
        print("(データなし)")
        return
    print(f"{'#':<5}{'ユーザー名':<22}{'利益(USD)':>16}{'取引量(USD)':>16}  アドレス")
    print("-" * 96)
    for i, u in enumerate(users, 1):
        name = (u.get("username", "") or "(no name)")[:20]
        profit = u.get("profit", 0.0)
        volume = u.get("volume", 0.0)
        addr = u.get("address", "")
        rank = u.get("rank", i)
        print(f"{rank:<5}{name:<22}{profit:>16,.2f}{volume:>16,.2f}  {addr}")


if __name__ == "__main__":
    all_boards = get_all_leaderboards()
    for key, users in all_boards.items():
        board_type, window = key.split("_", 1)
        label = config.WINDOW_LABELS.get(window, window)
        print_leaderboard(users, title=f"{label} / {board_type}")
