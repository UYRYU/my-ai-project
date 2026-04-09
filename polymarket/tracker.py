"""
Polymarket Tracker - 取引履歴の収集・保存モジュール
上位トレーダーの取引をAPIから取得し、CSVに蓄積する
"""

import os
import time
from typing import List

import pandas as pd
import requests
from loguru import logger

import config
from leaderboard import get_leaderboard


# 保存するCSVカラム
CSV_COLUMNS = [
    "trader",        # トレーダー名 or アドレス
    "market_id",     # マーケットID
    "market_title",  # マーケットタイトル
    "sport",         # スポーツ種別 (NBA/NFL/MLB/NHL/OTHER)
    "outcome",       # Yes/No などの結果選択肢
    "price",         # 約定価格 (オッズ 0.0〜1.0)
    "size",          # 取引サイズ (USDC等)
    "timestamp",     # 取引時刻 (UNIXタイムスタンプ)
    "result",        # 最終結果 (勝ち=1, 負け=0, 未確定=None)
]


def _request_with_retry(url: str, params: dict) -> list:
    """
    APIリクエストをリトライ付きで実行するヘルパー。
    レスポンスはJSONとしてパースして返す。
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
                f"[tracker] リクエスト失敗 (attempt {attempt}/{config.RETRY_COUNT}): {e}"
            )
            if attempt < config.RETRY_COUNT:
                time.sleep(config.RETRY_INTERVAL)
    raise RuntimeError(f"アクティビティ取得に失敗しました: {last_exc}")


def _detect_sport(title: str) -> str:
    """
    マーケットタイトルからスポーツ種別を推定する。
    該当しない場合は "OTHER" を返す。
    """
    if not title:
        return "OTHER"
    upper = title.upper()
    for tag in ["NBA", "NFL", "MLB", "NHL"]:
        if tag in upper:
            return tag
    # vs / Will の場合は一般スポーツとして扱う
    if " VS " in upper or upper.startswith("WILL "):
        return "SPORTS"
    return "OTHER"


def _is_sports_market(title: str) -> bool:
    """
    マーケットタイトルがスポーツ関連かを判定する。
    NBA/NFL/MLB/NHL/vs/Will のいずれかを含めばスポーツ扱い。
    """
    if not title:
        return False
    for kw in config.SPORTS_KEYWORDS:
        if kw.lower() in title.lower():
            return True
    return False


def get_user_trades(address: str) -> List[dict]:
    """
    指定アドレスの取引履歴を取得し、スポーツ関連のみフィルタして返す。

    Args:
        address: トレーダーのウォレットアドレス

    Returns:
        List[dict]: フィルタ済みの取引レコードのリスト (CSV_COLUMNS 準拠)
    """
    logger.info(f"取引履歴取得: {address}")

    params = {
        "user": address,
        "limit": 500,
    }

    try:
        raw = _request_with_retry(config.ACTIVITY_URL, params)
    except Exception as e:
        logger.error(f"取引履歴取得エラー [{address}]: {e}")
        return []

    # レート制限対策
    time.sleep(config.REQUEST_SLEEP)

    # レスポンスがリスト or {"data": [...]} のどちらにも対応
    if isinstance(raw, dict):
        activities = raw.get("data") or raw.get("activities") or []
    else:
        activities = raw

    if not isinstance(activities, list):
        logger.warning(f"予期しないレスポンス形式: {type(activities)}")
        return []

    trades: List[dict] = []
    for act in activities:
        # 取引系のみ対象 (TRADE / BUY / SELL)
        act_type = (act.get("type") or "").upper()
        if act_type and act_type not in ("TRADE", "BUY", "SELL"):
            continue

        # マーケットタイトルを取得
        title = (
            act.get("title")
            or act.get("eventTitle")
            or act.get("marketTitle")
            or act.get("question")
            or ""
        )

        # スポーツ関連のみフィルタ
        if not _is_sports_market(title):
            continue

        # 各フィールドを抽出 (APIの揺れに対応)
        market_id = (
            act.get("marketId")
            or act.get("conditionId")
            or act.get("market")
            or ""
        )
        outcome = act.get("outcome") or act.get("side") or ""
        price = act.get("price") or act.get("avgPrice") or 0
        size = act.get("size") or act.get("usdcSize") or act.get("amount") or 0
        timestamp = act.get("timestamp") or act.get("createdAt") or 0
        result = act.get("result")  # 未確定のことが多いので None でもOK

        try:
            price = float(price)
        except (TypeError, ValueError):
            price = 0.0
        try:
            size = float(size)
        except (TypeError, ValueError):
            size = 0.0
        try:
            timestamp = int(float(timestamp))
        except (TypeError, ValueError):
            timestamp = 0

        trades.append({
            "trader": address,
            "market_id": market_id,
            "market_title": title,
            "sport": _detect_sport(title),
            "outcome": outcome,
            "price": price,
            "size": size,
            "timestamp": timestamp,
            "result": result,
        })

    logger.info(f"  → スポーツ関連取引 {len(trades)} 件を抽出")
    return trades


def save_trades(trades: List[dict]) -> int:
    """
    取引リストを data/trades.csv に追記保存する。
    重複は market_id + trader + timestamp で判定して除外。

    Args:
        trades: 取引レコードのリスト

    Returns:
        int: 新規に追加された件数
    """
    if not trades:
        logger.info("保存する取引がありません")
        return 0

    # dataディレクトリを用意
    os.makedirs(os.path.dirname(config.DATA_PATH) or ".", exist_ok=True)

    new_df = pd.DataFrame(trades, columns=CSV_COLUMNS)

    if os.path.exists(config.DATA_PATH):
        try:
            existing_df = pd.read_csv(config.DATA_PATH)
        except Exception as e:
            logger.warning(f"既存CSVの読み込みに失敗 (新規作成します): {e}")
            existing_df = pd.DataFrame(columns=CSV_COLUMNS)

        # 重複キーの作成
        def _make_key(df: pd.DataFrame) -> pd.Series:
            return (
                df["market_id"].astype(str)
                + "|" + df["trader"].astype(str)
                + "|" + df["timestamp"].astype(str)
            )

        if not existing_df.empty:
            existing_keys = set(_make_key(existing_df).tolist())
            new_keys = _make_key(new_df)
            mask_unique = ~new_keys.isin(existing_keys)
            new_df = new_df[mask_unique]

        if new_df.empty:
            logger.info("全て重複のため、新規保存なし")
            return 0

        combined = pd.concat([existing_df, new_df], ignore_index=True)
    else:
        combined = new_df

    combined.to_csv(config.DATA_PATH, index=False)
    added = len(new_df)
    logger.info(f"{added} 件を {config.DATA_PATH} に保存 (累計 {len(combined)} 件)")
    return added


def collect_all() -> int:
    """
    リーダーボード上位者全員の取引を収集しCSVに保存する。

    Returns:
        int: 新規保存件数の合計
    """
    logger.info("=" * 50)
    logger.info("全上位者の取引収集を開始")
    logger.info("=" * 50)

    users = get_leaderboard()
    if not users:
        logger.error("リーダーボードが空のため収集を中止")
        return 0

    all_trades: List[dict] = []
    for user in users:
        address = user["address"]
        username = user.get("username", "")
        logger.info(f"→ {username} ({address})")

        trades = get_user_trades(address)

        # trader 欄をユーザー名に差し替え (アドレスしかなければそのまま)
        for t in trades:
            if username:
                t["trader"] = username
        all_trades.extend(trades)

    added = save_trades(all_trades)
    logger.info(f"収集完了: 新規 {added} 件 / 取得総数 {len(all_trades)} 件")
    return added


if __name__ == "__main__":
    collect_all()
