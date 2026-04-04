"""リスク管理モジュール。

全注文がここを通過し、以下のチェックを行う:
- Kill switch
- 日次損失上限
- 1回あたりの最大投入額
- 最大ポジションサイズ
- 同一マーケットへの連続発注制限
- シグナルレベルフィルタ
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.processor.signal_detector import Signal

logger = logging.getLogger(__name__)


class RiskManager:
    def __init__(
        self,
        max_order_usd: float = 50.0,
        max_position_usd: float = 200.0,
        max_daily_loss_usd: float = 100.0,
        min_signal_level: str = "STRONG",
        cooldown_sec: int = 300,
        kill_switch_env: bool = False,
        kill_switch_file: str = "KILL_SWITCH",
    ):
        self._max_order_usd = max_order_usd
        self._max_position_usd = max_position_usd
        self._max_daily_loss_usd = max_daily_loss_usd
        self._min_signal_level = min_signal_level.upper()
        self._cooldown_sec = cooldown_sec
        self._kill_switch_env = kill_switch_env
        self._kill_switch_file = kill_switch_file

        # 内部ステート
        self._daily_loss: float = 0.0
        self._daily_reset_date: str = ""
        self._positions: dict[str, float] = {}  # market_id -> total_usd
        self._last_order_time: dict[str, datetime] = {}  # market_id -> last time
        self._halted: bool = False

    @property
    def is_halted(self) -> bool:
        return self._halted

    @property
    def daily_loss(self) -> float:
        return self._daily_loss

    def check_kill_switch(self) -> bool:
        """Kill switchが有効ならTrueを返す。"""
        # .env フラグ
        if self._kill_switch_env:
            self._halted = True
            return True

        # 環境変数の動的チェック（.envを再起動なしで変更可能）
        if os.getenv("KILL_SWITCH", "false").lower() == "true":
            self._halted = True
            return True

        # ファイルベースの kill switch
        if Path(self._kill_switch_file).exists():
            self._halted = True
            return True

        return False

    def evaluate(self, signal: Signal, order_amount_usd: float) -> tuple[bool, str]:
        """注文がリスク条件を満たすか評価する。

        Returns:
            (allowed, reason): 注文可能ならTrue、不可ならFalseとその理由
        """
        # 日次リセット
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._daily_reset_date != today:
            self._daily_loss = 0.0
            self._daily_reset_date = today
            logger.info("日次リスクカウンターをリセット")

        # Kill switch
        if self.check_kill_switch():
            return False, "KILL_SWITCH が有効です。全注文を停止中。"

        # 手動停止
        if self._halted:
            return False, "リスクマネージャーにより停止中。"

        # シグナルレベルフィルタ
        if self._min_signal_level == "STRONG" and not signal.is_strong:
            return False, f"シグナルレベル不足: {signal.strength_label} < STRONG"

        # 1回あたりの最大投入額
        if order_amount_usd > self._max_order_usd:
            return False, (
                f"注文額 ${order_amount_usd:.2f} が上限 "
                f"${self._max_order_usd:.2f} を超過"
            )

        # 最大ポジションサイズ
        current_position = self._positions.get(signal.market_id, 0.0)
        if current_position + order_amount_usd > self._max_position_usd:
            return False, (
                f"ポジション上限: 既存 ${current_position:.2f} + "
                f"新規 ${order_amount_usd:.2f} > ${self._max_position_usd:.2f}"
            )

        # 日次損失上限
        if self._daily_loss >= self._max_daily_loss_usd:
            self._halted = True
            return False, (
                f"日次損失上限到達: ${self._daily_loss:.2f} >= "
                f"${self._max_daily_loss_usd:.2f}。自動停止。"
            )

        # 同一マーケットへの連続発注制限
        last_time = self._last_order_time.get(signal.market_id)
        if last_time:
            elapsed = (datetime.now(timezone.utc) - last_time).total_seconds()
            if elapsed < self._cooldown_sec:
                remaining = int(self._cooldown_sec - elapsed)
                return False, (
                    f"クールダウン中: {signal.market_id} "
                    f"(残り{remaining}秒)"
                )

        return True, "OK"

    def record_order(self, market_id: str, amount_usd: float) -> None:
        """発注成功時にステートを更新する。"""
        self._positions[market_id] = (
            self._positions.get(market_id, 0.0) + amount_usd
        )
        self._last_order_time[market_id] = datetime.now(timezone.utc)

    def record_loss(self, amount: float) -> None:
        """損失を記録する。"""
        self._daily_loss += amount
        if self._daily_loss >= self._max_daily_loss_usd:
            self._halted = True
            logger.warning(
                "日次損失上限に到達: $%.2f。自動停止。", self._daily_loss
            )

    def halt(self) -> None:
        """手動停止。"""
        self._halted = True
        logger.warning("リスクマネージャー: 手動停止")

    def resume(self) -> None:
        """停止解除。"""
        self._halted = False
        logger.info("リスクマネージャー: 再開")

    def get_status(self) -> dict:
        """現在のリスクステータスを返す。"""
        return {
            "halted": self._halted,
            "daily_loss": round(self._daily_loss, 2),
            "max_daily_loss": self._max_daily_loss_usd,
            "positions": {k: round(v, 2) for k, v in self._positions.items()},
            "max_order_usd": self._max_order_usd,
            "max_position_usd": self._max_position_usd,
        }
