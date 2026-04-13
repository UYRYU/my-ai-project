"""
Polymarket Tracker - 注文実行モジュール
ドライラン (ペーパートレード) とライブの両方に対応。

ドライラン: シグナルをログに記録し、ペーパートレードとして追跡
ライブ:    py-clob-client で CLOB API に注文を送信
"""

import os
from typing import List

from dotenv import load_dotenv
from loguru import logger

import risk

# .env ファイルから環境変数を読み込む
load_dotenv()


def is_dry_run() -> bool:
    """ドライランモードかどうかを判定する"""
    return os.getenv("DRY_RUN", "true").lower() in ("true", "1", "yes")


def execute_signals(signals: List[dict]) -> List[dict]:
    """
    シグナルに基づいてベットを実行する (ドライラン or ライブ)。

    Args:
        signals: strategy.enrich_signals() の結果

    Returns:
        実行されたトレードのリスト
    """
    if not signals:
        logger.info("[executor] 実行するシグナルなし")
        return []

    dry_run = is_dry_run()
    mode = "PAPER" if dry_run else "LIVE"
    logger.info(f"[executor] {mode}モードで {len(signals)} 件のシグナルを処理")

    executed = []
    for sig in signals:
        # リスクチェック
        can_trade, reason = risk.can_open_position()
        if not can_trade:
            logger.warning(f"[executor] ベット見送り: {reason}")
            break

        # ベットサイズを計算
        odds = sig.get("current_odds") or sig.get("trader_odds", 0.3)
        bet_size = risk.calculate_bet_size(odds)

        # 穴狙いフィルタの再確認
        if odds < risk.MIN_ODDS or odds > risk.MAX_ODDS:
            logger.info(f"[executor] オッズ範囲外のためスキップ: {odds:.3f}")
            continue

        if dry_run:
            trade = _execute_paper(sig, odds, bet_size)
        else:
            trade = _execute_live(sig, odds, bet_size)

        if trade:
            executed.append(trade)

    return executed


def _execute_paper(sig: dict, odds: float, bet_size: float) -> dict:
    """ペーパートレードとして記録する"""
    trade = risk.record_paper_trade(
        market_id=sig["market_id"],
        market_title=sig.get("market_title", ""),
        outcome=sig["outcome"],
        odds=odds,
        size=bet_size,
        trader=sig.get("trader", ""),
        trader_odds=sig.get("trader_odds", 0),
    )
    return trade


def _execute_live(sig: dict, odds: float, bet_size: float) -> dict:
    """
    CLOB API を使って実際に注文を出す。
    """
    logger.warning("[executor] ライブトレードは慎重に!")

    api_key = os.getenv("POLYMARKET_API_KEY")
    api_secret = os.getenv("POLYMARKET_API_SECRET")
    passphrase = os.getenv("POLYMARKET_PASSPHRASE")
    private_key = os.getenv("POLYMARKET_PRIVATE_KEY")

    if not all([api_key, api_secret, passphrase, private_key]):
        logger.error("[executor] 認証情報が不足しています (.env を確認)")
        return {}

    token_id = sig.get("token_id")
    if not token_id:
        logger.error(f"[executor] token_id がありません: {sig.get('market_title', '')[:40]}")
        return {}

    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import ApiCreds, MarketOrderArgs, OrderType

        client = ClobClient(
            "https://clob.polymarket.com",
            chain_id=137,
            key=private_key,
            creds=ApiCreds(
                api_key=api_key,
                api_secret=api_secret,
                api_passphrase=passphrase,
            ),
        )

        # マーケットオーダー (FOK: Fill or Kill)
        order_args = MarketOrderArgs(
            token_id=token_id,
            amount=bet_size,
            side="BUY",
        )
        signed_order = client.create_market_order(order_args)
        resp = client.post_order(signed_order, orderType=OrderType.FOK)

        logger.info(f"[LIVE] 注文送信: {sig['outcome']} @ ~{odds:.3f} ${bet_size:.2f}")
        logger.info(f"[LIVE] レスポンス: {resp}")

        # ペーパートレードにも記録 (追跡用)
        trade = risk.record_paper_trade(
            market_id=sig["market_id"],
            market_title=sig.get("market_title", ""),
            outcome=sig["outcome"],
            odds=odds,
            size=bet_size,
            trader=sig.get("trader", ""),
            trader_odds=sig.get("trader_odds", 0),
        )
        return trade

    except Exception as e:
        logger.exception(f"[LIVE] 注文失敗: {e}")
        return {}


def resolve_paper_trades() -> int:
    """
    オープン中のペーパートレードの勝敗を CLOB API で確認して決済する。

    Returns:
        決済されたトレード数
    """
    from resolver import get_market_result

    open_trades = risk.get_open_positions()
    if not open_trades:
        return 0

    resolved = 0
    for t in open_trades:
        result = get_market_result(t["market_id"], t["outcome"])
        if result is not None:
            risk.close_paper_trade(t["id"], won=(result == 1))
            resolved += 1

    if resolved:
        logger.info(f"[executor] {resolved} 件のペーパートレードを決済")
    return resolved
