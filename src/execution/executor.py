"""Executor: シグナルを受けて発注判断を行うオーケストレーター。

フロー:
1. Signal を受信
2. RiskManager で発注可否を判定
3. dry-run → ログ出力のみ
4. paper → PaperBroker で仮想約定
5. live → LiveBroker で実注文
6. 結果を DB に保存
"""

import logging
from datetime import datetime, timezone

from src.processor.signal_detector import Signal

from .live_broker import LiveBroker
from .models import Fill, Order, OrderStatus, PnLRecord, TradingMode
from .paper_broker import PaperBroker
from .risk_manager import RiskManager

logger = logging.getLogger(__name__)


class Executor:
    """シグナルに基づいて発注を実行するメインクラス。"""

    def __init__(
        self,
        mode: TradingMode,
        risk_manager: RiskManager,
        paper_broker: PaperBroker | None = None,
        live_broker: LiveBroker | None = None,
        allow_live: bool = False,
        order_amount_usd: float = 50.0,
    ):
        self._mode = mode
        self._risk = risk_manager
        self._paper = paper_broker or PaperBroker()
        self._live = live_broker
        self._allow_live = allow_live
        self._order_amount_usd = order_amount_usd

        # 統計
        self._total_orders = 0
        self._total_fills = 0
        self._total_rejects = 0
        self._total_pnl = 0.0
        self._orders: list[Order] = []
        self._fills: list[Fill] = []

    @property
    def mode(self) -> TradingMode:
        return self._mode

    @property
    def mode_label(self) -> str:
        return self._mode.value.upper()

    @property
    def stats(self) -> dict:
        return {
            "mode": self.mode_label,
            "total_orders": self._total_orders,
            "total_fills": self._total_fills,
            "total_rejects": self._total_rejects,
            "total_pnl": round(self._total_pnl, 2),
            "risk": self._risk.get_status(),
        }

    def _parse_signal_to_order(self, signal: Signal) -> Order:
        """シグナルからOrderを生成する。"""
        # direction は "Buy-Yes" / "Sell-No" 等
        parts = signal.direction.split("-")
        side = parts[0].lower() if len(parts) > 0 else "buy"
        outcome = parts[1] if len(parts) > 1 else "Yes"

        return Order(
            signal_market_id=signal.market_id,
            signal_direction=signal.direction,
            market_id=signal.market_id,
            market_title=signal.market_title,
            side=side,
            outcome=outcome,
            amount_usdc=self._order_amount_usd,
            limit_price=signal.avg_price,
            status=OrderStatus.PENDING,
            mode=self._mode,
        )

    async def process_signals(self, signals: list[Signal]) -> list[Order]:
        """シグナルリストを処理し、発注判断を行う。

        Returns:
            処理した Order のリスト（約定・拒否含む）
        """
        results: list[Order] = []

        for signal in signals:
            try:
                order = await self._process_one(signal)
                if order:
                    results.append(order)
            except Exception as e:
                logger.error(
                    "シグナル処理中にエラー: %s - %s", signal.market_id, e
                )

        return results

    async def _process_one(self, signal: Signal) -> Order | None:
        """1つのシグナルを処理する。"""
        order = self._parse_signal_to_order(signal)
        self._total_orders += 1

        # リスクチェック
        allowed, reason = self._risk.evaluate(signal, order.amount_usdc)
        if not allowed:
            order.status = OrderStatus.REJECTED
            order.reject_reason = reason
            self._total_rejects += 1
            self._orders.append(order)

            logger.info(
                "[%s] 注文拒否: %s %s $%.2f - %s",
                self.mode_label,
                order.market_title[:25],
                order.direction,
                order.amount_usdc,
                reason,
            )
            return order

        # モード別処理
        if self._mode == TradingMode.DRY_RUN:
            return await self._handle_dry_run(order)
        elif self._mode == TradingMode.PAPER:
            return await self._handle_paper(order, signal)
        elif self._mode == TradingMode.LIVE:
            return await self._handle_live(order, signal)

        return order

    async def _handle_dry_run(self, order: Order) -> Order:
        """Dry-run: 注文内容を表示するだけで送信しない。"""
        order.status = OrderStatus.CANCELLED
        order.reject_reason = "DRY-RUN: 送信せず表示のみ"
        self._orders.append(order)

        logger.info(
            "[DRY-RUN] 注文プレビュー: %s %s $%.2f @ %.4f",
            order.market_title[:30],
            order.direction,
            order.amount_usdc,
            order.limit_price,
        )
        return order

    async def _handle_paper(self, order: Order, signal: Signal) -> Order:
        """Paper: 仮想約定を行う。"""
        fill = await self._paper.submit_order(order)

        if fill:
            self._total_fills += 1
            self._fills.append(fill)
            self._risk.record_order(signal.market_id, order.amount_usdc)

        self._orders.append(order)
        return order

    async def _handle_live(self, order: Order, signal: Signal) -> Order:
        """Live: 実注文を送信する。"""
        if not self._allow_live:
            order.status = OrderStatus.REJECTED
            order.reject_reason = "ALLOW_LIVE_TRADING=false。Live取引は無効。"
            self._total_rejects += 1
            self._orders.append(order)
            logger.warning("[LIVE] Live取引が無効化されています。")
            return order

        if not self._live:
            order.status = OrderStatus.FAILED
            order.reject_reason = "LiveBrokerが未初期化。"
            self._orders.append(order)
            logger.error("[LIVE] LiveBrokerが設定されていません。")
            return order

        fill = await self._live.submit_order(order)

        if fill:
            self._total_fills += 1
            self._fills.append(fill)
            self._risk.record_order(signal.market_id, order.amount_usdc)

        self._orders.append(order)
        return order

    def get_recent_orders(self, limit: int = 20) -> list[Order]:
        return self._orders[-limit:]

    def get_recent_fills(self, limit: int = 20) -> list[Fill]:
        return self._fills[-limit:]
