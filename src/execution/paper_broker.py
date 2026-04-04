"""Paper（仮想）ブローカー。実資金を使わずにシミュレーション約定する。"""

import logging
import random

from .models import Fill, Order, OrderStatus, TradingMode

logger = logging.getLogger(__name__)


class PaperBroker:
    """仮想約定を行うブローカー。"""

    def __init__(self, slippage_bps: int = 50):
        """
        Args:
            slippage_bps: スリッページ（ベーシスポイント）。50 = 0.5%
        """
        self._slippage_bps = slippage_bps
        self._fill_count = 0

    async def submit_order(self, order: Order) -> Fill | None:
        """注文を仮想約定する。

        約定価格はlimit_priceにスリッページを加味した値。
        """
        try:
            # スリッページ計算
            slippage = self._slippage_bps / 10000
            if order.side == "buy":
                fill_price = order.limit_price * (1 + slippage)
            else:
                fill_price = order.limit_price * (1 - slippage)
            fill_price = round(min(max(fill_price, 0.01), 0.99), 4)

            self._fill_count += 1

            fill = Fill(
                order_id=order.order_id,
                market_id=order.market_id,
                side=order.side,
                outcome=order.outcome,
                amount_usdc=order.amount_usdc,
                fill_price=fill_price,
                mode=TradingMode.PAPER,
            )

            order.status = OrderStatus.FILLED

            logger.info(
                "[PAPER] 約定: %s %s-%s $%.2f @ %.4f (order=%s)",
                order.market_title[:30],
                order.side,
                order.outcome,
                order.amount_usdc,
                fill_price,
                order.order_id,
            )
            return fill

        except Exception as e:
            order.status = OrderStatus.FAILED
            order.reject_reason = str(e)
            logger.error("[PAPER] 約定失敗: %s - %s", order.order_id, e)
            return None

    @property
    def fill_count(self) -> int:
        return self._fill_count
