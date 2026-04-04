"""Paper（仮想）ブローカー。実資金を使わずにシミュレーション約定する。

Paperモデル:
  v2_binary (デフォルト) — Polymarketの二値収束モデル
    - entry_price を「勝率」とみなす
    - Buy: entry_price の確率で的中 (exit=1.0)、(1-entry_price) で外れ (exit=0.0)
    - Sell: (1-entry_price) の確率で的中 (exit=0.0)、entry_price で外れ (exit=1.0)
    - PnL = (exit - entry) * shares （Buy）
    - PnL = (entry - exit) * shares （Sell）

  v1_random (レガシー) — 旧ランダム ±15% モデル
    - exit_price = entry ± uniform(-0.15, 0.15)
    - 勝率が約50%に収束し、市場特性を反映しない

損益定義:
  ┌─────────┬─────────────┬──────────────────────────────────┐
  │ Side    │ Outcome     │ PnL の意味                        │
  ├─────────┼─────────────┼──────────────────────────────────┤
  │ Buy-Yes │ 的中(exit=1)│ (1.0 - entry) * shares → 利益    │
  │ Buy-Yes │ 外れ(exit=0)│ (0.0 - entry) * shares → 全損    │
  │ Buy-No  │ 的中(exit=1)│ (1.0 - entry) * shares → 利益    │
  │ Buy-No  │ 外れ(exit=0)│ (0.0 - entry) * shares → 全損    │
  │ Sell-Yes│ 的中(exit=0)│ (entry - 0.0) * shares → 利益    │
  │ Sell-Yes│ 外れ(exit=1)│ (entry - 1.0) * shares → 損失    │
  │ Sell-No │ 的中(exit=0)│ (entry - 0.0) * shares → 利益    │
  │ Sell-No │ 外れ(exit=1)│ (entry - 1.0) * shares → 損失    │
  └─────────┴─────────────┴──────────────────────────────────┘

環境変数:
  LEGACY_PAPER_MODEL=true → v1_random を使用（デフォルト: false → v2_binary）
"""

import logging
import os
import random
from datetime import datetime, timezone

from .models import Fill, Order, OrderStatus, PaperTrade, TradingMode

logger = logging.getLogger(__name__)


def _is_legacy_model() -> bool:
    """LEGACY_PAPER_MODEL 環境変数でモデルを切り替える。"""
    return os.getenv("LEGACY_PAPER_MODEL", "false").lower() == "true"


class PaperBroker:
    """仮想約定を行うブローカー。"""

    def __init__(
        self,
        slippage_bps: int = 50,
        hold_minutes_range: tuple[int, int] = (5, 120),
        use_legacy: bool | None = None,
    ):
        """
        Args:
            slippage_bps: スリッページ（ベーシスポイント）。50 = 0.5%
            hold_minutes_range: 仮想保有時間の範囲（分）
            use_legacy: 明示的にレガシーモデルを使うか。None の場合は環境変数で判定。
        """
        self._slippage_bps = slippage_bps
        self._hold_min, self._hold_max = hold_minutes_range
        self._fill_count = 0
        self._use_legacy = use_legacy if use_legacy is not None else _is_legacy_model()

    @property
    def model_version(self) -> str:
        return "v1_random" if self._use_legacy else "v2_binary"

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
        """約定済みのFillに対して仮想決済をシミュレーションする。"""
        if self._use_legacy:
            return self._simulate_exit_v1_random(fill, order, signal_time)
        return self._simulate_exit_v2_binary(fill, order, signal_time)

    # ── v2: Binary Outcome Model ─────────────────────────────

    def _simulate_exit_v2_binary(
        self, fill: Fill, order: Order, signal_time: datetime
    ) -> PaperTrade:
        """二値収束モデル: entry_price を確率とみなし、的中 or 外れで決済。

        Polymarketの本質:
        - トークン価格 = マーケットが Yes/No に解決する確率の市場推定値
        - Buy @ 0.30 → 30% の確率で $1.0 になる → 期待利益 = 0.7*0.3 - 0.3*0.7 = 0
        - シグナルが正しければ実際の勝率 > entry_price → 期待値プラス
        """
        entry_price = fill.fill_price
        holding_minutes = random.uniform(self._hold_min, self._hold_max)
        shares = fill.amount_usdc / entry_price if entry_price > 0 else 0

        # entry_price をそのまま勝率として使用
        # buy: entry_price が低いほど当たりやすい（安く買える = 低確率イベント）
        #       ではなく、entry_price = 市場が見積もる勝率そのもの
        # sell: 価格が下がる（=イベント不成立）ことに賭ける
        if fill.side == "buy":
            # Buy: entry_price の確率で的中 → exit=1.0、外れ → exit=0.0
            win_probability = entry_price
            if random.random() < win_probability:
                exit_price = 0.99  # 的中（最大値クランプ）
                pnl = (0.99 - entry_price) * shares
            else:
                exit_price = 0.01  # 外れ（最小値クランプ）
                pnl = (0.01 - entry_price) * shares
        else:
            # Sell: (1 - entry_price) の確率で的中 → exit=0.0 (イベント不成立)
            #        entry_price の確率で外れ → exit=1.0 (イベント成立)
            win_probability = 1.0 - entry_price
            if random.random() < win_probability:
                exit_price = 0.01  # イベント不成立（Sell側の勝ち）
                pnl = (entry_price - 0.01) * shares
            else:
                exit_price = 0.99  # イベント成立（Sell側の負け）
                pnl = (entry_price - 0.99) * shares

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
            model_version="v2_binary",
        )

        logger.info(
            "[PAPER-v2] 仮想決済: %s %s entry=%.4f exit=%.4f PnL=$%.2f (%s, p=%.2f)",
            order.market_title[:25],
            direction,
            entry_price,
            exit_price,
            pnl,
            result,
            win_probability,
        )

        return paper_trade

    # ── v1: Legacy Random Model ──────────────────────────────

    def _simulate_exit_v1_random(
        self, fill: Fill, order: Order, signal_time: datetime
    ) -> PaperTrade:
        """旧ランダムモデル: entry ± 15% のランダム変動。"""
        entry_price = fill.fill_price
        holding_minutes = random.uniform(self._hold_min, self._hold_max)

        price_change = random.uniform(-0.15, 0.15)
        if fill.side == "buy":
            exit_price = entry_price + price_change
        else:
            exit_price = entry_price - price_change
        exit_price = round(min(max(exit_price, 0.01), 0.99), 4)

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
            model_version="v1_random",
        )

        logger.info(
            "[PAPER-v1] 仮想決済: %s %s entry=%.4f exit=%.4f PnL=$%.2f (%s)",
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
