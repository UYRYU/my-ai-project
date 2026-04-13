"""
Polymarket Tracker - 勝敗結果の自動更新モジュール
Gamma API からマーケットの決着情報を取得し、CSVの result カラムを更新する。

Gamma API レスポンスの関連フィールド:
  - closed: bool  (マーケットが閉じたか)
  - outcome: str  (決着した結果。"Yes" / "No" / 具体的な結果名)
  - outcomePrices: str  (例: "[1, 0]" → Yesが勝ち, "[0, 1]" → Noが勝ち)
  - conditionId: str  (マーケットの condition ID)
"""

import json
import time
from typing import Dict, Optional

import pandas as pd
import requests
from loguru import logger

import config


def _request_with_retry(url: str, params: dict = None) -> dict:
    """APIリクエストをリトライ付きで実行する"""
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
                f"[resolver] リクエスト失敗 (attempt {attempt}/{config.RETRY_COUNT}): {e}"
            )
            if attempt < config.RETRY_COUNT:
                time.sleep(config.RETRY_INTERVAL)
    raise RuntimeError(f"マーケット情報取得に失敗: {last_exc}")


def _fetch_market_by_condition(condition_id: str) -> Optional[dict]:
    """
    conditionId でマーケット情報を取得する。
    Gamma API: GET /markets?condition_id={id}
    """
    try:
        data = _request_with_retry(
            config.MARKETS_URL,
            params={"condition_id": condition_id, "limit": 1},
        )
    except Exception:
        return None

    if isinstance(data, list) and data:
        return data[0]
    if isinstance(data, dict):
        items = data.get("data") or data.get("markets") or []
        if items:
            return items[0]
    return None


def _fetch_market_by_id(market_id: str) -> Optional[dict]:
    """
    数値IDまたはslugでマーケット情報を取得する。
    Gamma API: GET /markets/{id}
    """
    try:
        data = _request_with_retry(f"{config.MARKETS_URL}/{market_id}")
    except Exception:
        return None

    if isinstance(data, dict) and data.get("id"):
        return data
    return None


def _fetch_market_by_slug(slug: str) -> Optional[dict]:
    """
    slug でマーケット情報を取得する。
    Gamma API: GET /markets?slug={slug}
    """
    try:
        data = _request_with_retry(
            config.MARKETS_URL,
            params={"slug": slug, "limit": 1},
        )
    except Exception:
        return None

    if isinstance(data, list) and data:
        return data[0]
    return None


def get_market_info(market_id: str) -> Optional[dict]:
    """
    market_id からマーケット情報を取得する。
    activity API が返す ID の形式が不明なため、複数の方法で試す:
      1. condition_id として検索
      2. 数値 ID として直接取得
      3. slug として検索
    """
    if not market_id:
        return None

    # 0x で始まるならcondition_id
    if market_id.startswith("0x"):
        market = _fetch_market_by_condition(market_id)
        if market:
            return market

    # 数値ならID直接
    if market_id.isdigit():
        market = _fetch_market_by_id(market_id)
        if market:
            return market

    # それ以外はまず condition_id、なければ slug
    market = _fetch_market_by_condition(market_id)
    if market:
        return market

    market = _fetch_market_by_slug(market_id)
    if market:
        return market

    return None


def _parse_outcome_prices(prices_str: str) -> Optional[list]:
    """
    outcomePrices フィールドをパースする。
    例: "[1, 0]" → [1.0, 0.0]
    """
    if not prices_str:
        return None
    try:
        prices = json.loads(prices_str)
        return [float(p) for p in prices]
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def determine_result(trader_outcome: str, market_info: dict) -> Optional[int]:
    """
    トレーダーの選択と市場の決着結果を照合して勝敗を判定する。

    Args:
        trader_outcome: トレーダーが選んだ方 ("Yes" / "No" 等)
        market_info: Gamma API のマーケット情報

    Returns:
        1 = 勝ち, 0 = 負け, None = 未決着 or 判定不能
    """
    # マーケットが閉じていなければ未決着
    if not market_info.get("closed"):
        return None

    # 方法1: outcome フィールドで判定
    market_outcome = market_info.get("outcome") or ""
    if market_outcome:
        trader_upper = trader_outcome.strip().upper()
        market_upper = market_outcome.strip().upper()

        if trader_upper == market_upper:
            return 1  # 勝ち
        # Yes/No の単純比較
        if trader_upper in ("YES", "NO") and market_upper in ("YES", "NO"):
            return 0 if trader_upper != market_upper else 1

    # 方法2: outcomePrices で判定
    prices = _parse_outcome_prices(market_info.get("outcomePrices", ""))
    if prices and len(prices) >= 2:
        # [1, 0] = Yes勝ち, [0, 1] = No勝ち
        yes_won = prices[0] > 0.5
        trader_upper = trader_outcome.strip().upper()
        if trader_upper == "YES":
            return 1 if yes_won else 0
        elif trader_upper == "NO":
            return 0 if yes_won else 1

    # outcome フィールドに具体的な結果名が入っている場合 (部分一致)
    if market_outcome and trader_outcome:
        if trader_outcome.lower() in market_outcome.lower():
            return 1
        # 決着はしているが一致しない
        return 0

    return None


def update_results() -> Dict[str, int]:
    """
    CSVの result が空のレコードについて、Gamma API からマーケット情報を取得し
    勝敗を判定して更新する。

    Returns:
        {"checked": N, "resolved": N, "unresolved": N, "errors": N}
    """
    logger.info("=" * 50)
    logger.info("勝敗結果の更新を開始")
    logger.info("=" * 50)

    try:
        df = pd.read_csv(config.DATA_PATH)
    except Exception as e:
        logger.error(f"CSV読み込みエラー: {e}")
        return {"checked": 0, "resolved": 0, "unresolved": 0, "errors": 1}

    if df.empty:
        logger.info("取引データがありません")
        return {"checked": 0, "resolved": 0, "unresolved": 0, "errors": 0}

    # result が空 (NaN) のレコードだけ対象
    mask_empty = df["result"].isna()
    pending_count = mask_empty.sum()
    logger.info(f"result 未設定: {pending_count} 件 / 全 {len(df)} 件")

    if pending_count == 0:
        logger.info("更新対象なし")
        return {"checked": 0, "resolved": 0, "unresolved": 0, "errors": 0}

    # ユニークな market_id を取得 (1マーケットにつき1回だけAPI呼び出し)
    pending_markets = df.loc[mask_empty, "market_id"].unique()
    logger.info(f"マーケット数: {len(pending_markets)}")

    # マーケット情報のキャッシュ
    market_cache: Dict[str, Optional[dict]] = {}
    stats = {"checked": 0, "resolved": 0, "unresolved": 0, "errors": 0}

    for i, mid in enumerate(pending_markets):
        mid_str = str(mid)
        if not mid_str or mid_str == "nan":
            continue

        stats["checked"] += 1

        if mid_str not in market_cache:
            logger.info(
                f"  [{i+1}/{len(pending_markets)}] マーケット取得: {mid_str[:40]}..."
            )
            market_cache[mid_str] = get_market_info(mid_str)
            time.sleep(config.REQUEST_SLEEP)  # レート制限対策

        market = market_cache[mid_str]
        if market is None:
            stats["errors"] += 1
            continue

        # このマーケットに関連する全レコードを更新
        market_mask = mask_empty & (df["market_id"].astype(str) == mid_str)
        for idx in df.index[market_mask]:
            trader_outcome = str(df.at[idx, "outcome"] or "")
            result = determine_result(trader_outcome, market)

            if result is not None:
                df.at[idx, "result"] = result
                stats["resolved"] += 1
            else:
                stats["unresolved"] += 1

    # CSVに書き戻し
    df.to_csv(config.DATA_PATH, index=False)
    logger.info(
        f"更新完了: "
        f"確認 {stats['checked']} 市場 / "
        f"決着 {stats['resolved']} 件 / "
        f"未決着 {stats['unresolved']} 件 / "
        f"エラー {stats['errors']} 件"
    )
    return stats


if __name__ == "__main__":
    update_results()
