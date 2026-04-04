"""Paper（仮想）ブローカー。実資金を使わずにシミュレーション約定する。"""

import logging
import random
from datetime import datetime, timezone

from .models import Fill, Order, OrderStatus, PaperTrade, TradingMode

logger = logging.getLogger(__name__)


class PaperBroker:
    """仮想約定を行うブローカー。"""

    def __init__(self, slippage_bps: int = 50, hold_minutes_range: tuple[int, int] = (5, 120)):
        """
        Args:
            slippage_bps: スリッページ（ベーシスポイント）。50 = 0.5%
            hold_minutes_range: 仮想保有時間の範囲（分）
        """
        self._slippage_bps = slippage_bps
        self._hold_min, self._hold_max = hold_minutes_range
        self._fill_count = 0

    async def submit_order(self, order: Order) -> Fill | None:
        """注文を仮想約定する。"""
        try:
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

    def simulate_exit(self, fill: Fill, order: Order, signal_time: datetime) -> PaperTrade:
        """約定済みのFillに対して仮想決済をシミュレーションする。

        Polymarketの二値オプション特性:
        - buy の場合、最終的に 1.00（的中）or 0.00（外れ）に収束
        - 途中売却をシミュレーション: entry_price ± ランダム変動
        """
        entry_price = fill.fill_price
        holding_minutes = random.uniform(self._hold_min, self._hold_max)

        # 仮想exit価格: entry から ±15% の範囲で変動
        price_change = random.uniform(-0.15, 0.15)
        if fill.side == "buy":
            exit_price = entry_price + price_change
        else:
            # sell の場合は反転（売った後に価格が下がれば利益）
            exit_price = entry_price - price_change
        exit_price = round(min(max(exit_price, 0.01), 0.99), 4)

        # PnL計算
        # buy: (exit - entry) * shares, shares = amount / entry_price
        # sell: (entry - exit) * shares
        shares = fill.amount_usdc / entry_price if entry_price > 0 else 0
        if fill.side == "buy":
            pnl = (exit_price - entry_price) * shares
        else:
            pnl = (entry_price - exit_price) * shares
        pnl = round(pnl, 2)

        result = "win" if pnl > 0 else "loss"
        direction = f"{order.side.capitalize()}-{order.outcome}"

        paper_trade = PaperTrade(
            order_id=order.order_id,
            signal_time=signal_time,
            market_id=fill.market_id,
            market_title=order.market_title,
            direction=direction,
            entry_price=entry_price,
            entry_amount_usd=fill.amount_usdc,
            exit_price=exit_price,
            pnl_usd=pnl,
            holding_minutes=round(holding_minutes, 1),
            result=result,
        )

        logger.info(
            "[PAPER] 仮想決済: %s %s entry=%.4f exit=%.4f PnL=$%.2f (%s)",
            order.market_title[:25],
            direction,
            entry_price,
            exit_price,
            pnl,
            result,
        )

        return paper_trade

    @property
    def fill_count(self) -> int:
        return self._fill_count
