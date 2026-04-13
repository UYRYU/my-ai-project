"""
Polymarket Tracker - 勝敗結果の自動更新モジュール
CLOB API / Gamma API からマーケットの決着情報を取得し、CSVの result カラムを更新する。

CLOB API (優先): GET https://clob.polymarket.com/markets/{condition_id}
  - tokens[].outcome: "Yes" / "No"
  - tokens[].winner: true/false  (決着していれば)
  - closed: bool

Gamma API (フォールバック): GET https://gamma-api.polymarket.com/markets?condition_id={id}
  - outcome: str  ("Yes" / "No")
  - outcomePrices: str  ("[1, 0]" / "[0, 1]")
  - closed: bool
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


# ===== CLOB API (優先) =====

def _fetch_clob_market(condition_id: str) -> Optional[dict]:
    """
    CLOB API でマーケット情報を取得する。
    GET https://clob.polymarket.com/markets/{condition_id}
    tokens[].winner で勝敗が明示されている。
    """
    try:
        data = _request_with_retry(f"{config.CLOB_URL}/{condition_id}")
    except Exception:
        return None

    if isinstance(data, dict) and data.get("condition_id"):
        return data
    return None


def _determine_result_clob(trader_outcome: str, market: dict) -> Optional[int]:
    """
    CLOB API のレスポンスから勝敗を判定する。
    tokens 配列の winner フィールドを使う。
    """
    if not market.get("closed"):
        return None

    tokens = market.get("tokens") or []
    if not tokens:
        return None

    # winner=true のトークンを探す
    winning_outcome = None
    any_winner = False
    for token in tokens:
        if token.get("winner"):
            any_winner = True
            winning_outcome = (token.get("outcome") or "").strip().upper()
            break

    # まだ決着していない (全トークンの winner=false)
    if not any_winner:
        return None

    trader_upper = trader_outcome.strip().upper()
    if trader_upper == winning_outcome:
        return 1  # 勝ち
    else:
        return 0  # 負け


# ===== Gamma API (フォールバック) =====

def _fetch_gamma_market_by_condition(condition_id: str) -> Optional[dict]:
    """conditionId で Gamma API からマーケット情報を取得する"""
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


def _fetch_gamma_market_by_id(market_id: str) -> Optional[dict]:
    """数値ID で Gamma API からマーケット情報を取得する"""
    try:
        data = _request_with_retry(f"{config.MARKETS_URL}/{market_id}")
    except Exception:
        return None

    if isinstance(data, dict) and data.get("id"):
        return data
    return None


def _parse_outcome_prices(prices_str: str) -> Optional[list]:
    """outcomePrices をパースする: "[1, 0]" → [1.0, 0.0]"""
    if not prices_str:
        return None
    try:
        prices = json.loads(prices_str)
        return [float(p) for p in prices]
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _determine_result_gamma(trader_outcome: str, market: dict) -> Optional[int]:
    """
    Gamma API のレスポンスから勝敗を判定する。
    outcome / outcomePrices フィールドを使う。
    """
    if not market.get("closed"):
        return None

    trader_upper = trader_outcome.strip().upper()

    # 方法1: outcome フィールド
    market_outcome = (market.get("outcome") or "").strip().upper()
    if market_outcome:
        if trader_upper == market_outcome:
            return 1
        if trader_upper in ("YES", "NO") and market_outcome in ("YES", "NO"):
            return 0 if trader_upper != market_outcome else 1

    # 方法2: outcomePrices
    prices = _parse_outcome_prices(market.get("outcomePrices", ""))
    if prices and len(prices) >= 2:
        yes_won = prices[0] > 0.5
        if trader_upper == "YES":
            return 1 if yes_won else 0
        elif trader_upper == "NO":
            return 0 if yes_won else 1

    # 部分一致で判定
    if market_outcome and trader_outcome:
        if trader_outcome.lower() in market_outcome.lower():
            return 1
        return 0

    return None


# ===== メイン処理 =====

def get_market_result(market_id: str, trader_outcome: str) -> Optional[int]:
    """
    マーケットIDとトレーダーの選択から勝敗を判定する。
    1. CLOB API (tokens[].winner で確実に判定)
    2. Gamma API (フォールバック)

    Returns:
        1=勝ち, 0=負け, None=未決着/判定不能
    """
    if not market_id or not trader_outcome:
        return None

    mid = str(market_id)

    # 1. CLOB API で試す (condition_id 形式: 0x... が一般的)
    clob_market = _fetch_clob_market(mid)
    if clob_market:
        result = _determine_result_clob(trader_outcome, clob_market)
        if result is not None:
            return result

    # 2. Gamma API で試す
    if mid.startswith("0x"):
        gamma_market = _fetch_gamma_market_by_condition(mid)
    elif mid.isdigit():
        gamma_market = _fetch_gamma_market_by_id(mid)
    else:
        gamma_market = _fetch_gamma_market_by_condition(mid)

    if gamma_market:
        result = _determine_result_gamma(trader_outcome, gamma_market)
        if result is not None:
            return result

    return None


def update_results() -> Dict[str, int]:
    """
    CSVの result が空のレコードについて、CLOB / Gamma API から
    マーケットの決着情報を取得し勝敗を判定して更新する。

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
    pending_count = int(mask_empty.sum())
    logger.info(f"result 未設定: {pending_count} 件 / 全 {len(df)} 件")

    if pending_count == 0:
        logger.info("更新対象なし")
        return {"checked": 0, "resolved": 0, "unresolved": 0, "errors": 0}

    # ユニークな market_id ごとに処理 (API呼び出しを最小化)
    pending_markets = df.loc[mask_empty, "market_id"].dropna().unique()
    logger.info(f"確認対象マーケット数: {len(pending_markets)}")

    # 結果キャッシュ: {(market_id, outcome) -> result}
    result_cache: Dict[str, Dict[str, Optional[int]]] = {}
    stats = {"checked": 0, "resolved": 0, "unresolved": 0, "errors": 0}

    for i, mid in enumerate(pending_markets):
        mid_str = str(mid)
        if not mid_str or mid_str == "nan":
            continue

        stats["checked"] += 1

        if i % 10 == 0:
            logger.info(f"  進捗: {i+1}/{len(pending_markets)} マーケット")

        # このマーケットのユニークな outcome を取得
        market_mask = mask_empty & (df["market_id"].astype(str) == mid_str)
        outcomes = df.loc[market_mask, "outcome"].dropna().unique()

        for outcome in outcomes:
            outcome_str = str(outcome)
            cache_key = f"{mid_str}|{outcome_str}"

            if cache_key not in result_cache:
                result = get_market_result(mid_str, outcome_str)
                result_cache[cache_key] = result
                time.sleep(config.REQUEST_SLEEP)  # レート制限対策
            else:
                result = result_cache[cache_key]

            # 該当レコードを更新
            update_mask = market_mask & (df["outcome"].astype(str) == outcome_str)
            match_count = int(update_mask.sum())

            if result is not None:
                df.loc[update_mask, "result"] = result
                stats["resolved"] += match_count
            else:
                stats["unresolved"] += match_count

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
