"""シグナル検知モジュール。

MVPシグナル条件:
- 同一マーケット
- 指定時間窓内（デフォルト5分）
- 指定数以上のウォレット（デフォルト3）
- 同方向の注文
- 一定金額以上なら強シグナル
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from src.collector.base import Trade

logger = logging.getLogger(__name__)


@dataclass
class Signal:
    market_id: str
    market_title: str
    direction: str  # e.g. "Buy-Yes"
    wallets: list[str]
    total_amount_usdc: float
    avg_price: float
    first_trade_time: datetime
    last_trade_time: datetime
    is_strong: bool = False
    detected_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def wallet_count(self) -> int:
        return len(self.wallets)

    @property
    def strength_label(self) -> str:
        return "STRONG" if self.is_strong else "NORMAL"


class SignalDetector:
    """時間窓内の同方向取引をクラスタリングしてシグナルを検知する。"""

    def __init__(
        self,
        time_window_sec: int = 300,
        min_wallets: int = 3,
        strong_amount_threshold: float = 1000.0,
    ):
        self._time_window = timedelta(seconds=time_window_sec)
        self._min_wallets = min_wallets
        self._strong_threshold = strong_amount_threshold
        # market_id -> direction -> list[Trade]
        self._buffer: dict[str, dict[str, list[Trade]]] = defaultdict(
            lambda: defaultdict(list)
        )

    def ingest(self, trades: list[Trade]) -> list[Signal]:
        """取引を取り込み、シグナル条件を満たすものを返す。"""
        now = datetime.now(timezone.utc)
        cutoff = now - self._time_window

        for trade in trades:
            direction = trade.direction
            self._buffer[trade.market_id][direction].append(trade)

        # 古い取引を除去し、シグナルを検知
        signals: list[Signal] = []
        for market_id, directions in self._buffer.items():
            for direction, buffered_trades in directions.items():
                # 時間窓外の取引を除去
                buffered_trades[:] = [
                    t for t in buffered_trades if t.timestamp >= cutoff
                ]

                # ユニークウォレットを集計
                unique_wallets = list(
                    {t.wallet_address for t in buffered_trades}
                )
                if len(unique_wallets) < self._min_wallets:
                    continue

                total_amount = sum(t.amount_usdc for t in buffered_trades)
                prices = [t.price for t in buffered_trades if t.price > 0]
                avg_price = sum(prices) / len(prices) if prices else 0
                timestamps = [t.timestamp for t in buffered_trades]

                signal = Signal(
                    market_id=market_id,
                    market_title=buffered_trades[0].market_title,
                    direction=direction,
                    wallets=unique_wallets,
                    total_amount_usdc=round(total_amount, 2),
                    avg_price=round(avg_price, 4),
                    first_trade_time=min(timestamps),
                    last_trade_time=max(timestamps),
                    is_strong=total_amount >= self._strong_threshold,
                )
                signals.append(signal)
                logger.info(
                    "シグナル検知: %s [%s] %d wallets $%.2f (%s)",
                    market_id,
                    direction,
                    signal.wallet_count,
                    total_amount,
                    signal.strength_label,
                )

        return signals

    def clear(self) -> None:
        self._buffer.clear()
