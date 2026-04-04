"""Live ブローカー。Polymarket CLOB クライアントを使用して実注文を送信する。

NOTE: 実運用時は py-clob-client パッケージが必要。
      pip install py-clob-client
      現在はインターフェースのみ定義し、実装は段階的に追加する。
"""

import logging

from .models import Fill, Order, OrderStatus, TradingMode

logger = logging.getLogger(__name__)


class LiveBroker:
    """Polymarket CLOB API経由で実注文を送信するブローカー。

    ALLOW_LIVE_TRADING=true かつ TRADING_MODE=live の場合のみ有効。
    """

    def __init__(
        self,
        private_key: str = "",
        api_key: str = "",
        api_secret: str = "",
        api_passphrase: str = "",
    ):
        self._private_key = private_key
        self._api_key = api_key
        self._api_secret = api_secret
        self._api_passphrase = api_passphrase
        self._client = None
        self._fill_count = 0

    async def initialize(self) -> None:
        """CLOB クライアントを初期化する。"""
        if not self._private_key:
            logger.warning(
                "[LIVE] POLY_PRIVATE_KEY が未設定。Live取引は無効です。"
            )
            return

        try:
            # py-clob-client が利用可能な場合にのみインポート
            from py_clob_client.client import ClobClient

            self._client = ClobClient(
                host="https://clob.polymarket.com",
                key=self._private_key,
                chain_id=137,  # Polygon
            )
            # API Key認証の設定
            if self._api_key:
                self._client.set_api_creds(
                    self._client.create_or_derive_api_creds()
                )
            logger.info("[LIVE] CLOB クライアント初期化完了")

        except ImportError:
            logger.error(
                "[LIVE] py-clob-client が未インストール。"
                "pip install py-clob-client を実行してください。"
            )
            self._client = None
        except Exception as e:
            logger.error("[LIVE] CLOBクライアント初期化失敗: %s", e)
            self._client = None

    async def submit_order(self, order: Order) -> Fill | None:
        """実注文を送信する。"""
        if not self._client:
            order.status = OrderStatus.FAILED
            order.reject_reason = "CLOBクライアント未初期化"
            logger.error("[LIVE] クライアント未初期化。注文をスキップ。")
            return None

        try:
            logger.info(
                "[LIVE] 注文送信中: %s %s-%s $%.2f @ %.4f",
                order.market_title[:30],
                order.side,
                order.outcome,
                order.amount_usdc,
                order.limit_price,
            )

            # CLOB APIで注文を作成・送信
            # NOTE: 実際のtoken_idはマーケット情報から取得する必要がある
            order_args = {
                "token_id": order.market_id,
                "price": order.limit_price,
                "size": order.amount_usdc,
                "side": "BUY" if order.side == "buy" else "SELL",
            }

            signed_order = self._client.create_order(order_args)
            response = self._client.post_order(signed_order)

            if response and response.get("success"):
                self._fill_count += 1
                fill = Fill(
                    order_id=order.order_id,
                    market_id=order.market_id,
                    side=order.side,
                    outcome=order.outcome,
                    amount_usdc=order.amount_usdc,
                    fill_price=order.limit_price,
                    mode=TradingMode.LIVE,
                )
                order.status = OrderStatus.FILLED
                logger.info("[LIVE] 約定成功: %s", order.order_id)
                return fill
            else:
                order.status = OrderStatus.REJECTED
                order.reject_reason = str(response)
                logger.warning("[LIVE] 注文拒否: %s - %s", order.order_id, response)
                return None

        except Exception as e:
            order.status = OrderStatus.FAILED
            order.reject_reason = str(e)
            logger.error("[LIVE] 注文失敗: %s - %s", order.order_id, e)
            return None

    async def close(self) -> None:
        """クリーンアップ。"""
        self._client = None

    @property
    def fill_count(self) -> int:
        return self._fill_count
