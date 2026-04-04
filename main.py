"""Polymarket Wallet Tracker Terminal - メインエントリーポイント。"""

import asyncio
import logging
import signal
import sys

from src.collector import MockCollector, PolymarketCollector
from src.config import Config
from src.notifier import DiscordNotifier
from src.processor import SignalDetector, normalize_trades
from src.storage import Database
from src.ui import TerminalUI

logger = logging.getLogger(__name__)


class WalletTracker:
    """メインのトラッカーオーケストレーター。"""

    def __init__(self, config: Config):
        self.config = config
        self.ui = TerminalUI()
        self.db = Database(config.db_path)
        self.notifier = DiscordNotifier(config.discord_webhook_url)
        self.detector = SignalDetector(
            time_window_sec=config.signal_time_window_sec,
            min_wallets=config.signal_min_wallets,
            strong_amount_threshold=config.signal_strong_amount_threshold,
        )

        if config.data_source == "mock":
            self.collector = MockCollector(cluster_mode=True)
        else:
            self.collector = PolymarketCollector()

        self._running = False

    async def start(self) -> None:
        """トラッカーを開始する。"""
        self.ui.show_banner()

        # DB初期化
        await self.db.initialize()
        self.ui.show_info("データベース初期化完了")

        # ウォレット表示
        self.ui.show_wallets(self.config.wallets)

        if not self.config.wallets:
            self.ui.show_error("監視ウォレットが登録されていません。wallets_seed.csvを確認してください。")
            return

        source_label = "MOCK" if self.config.data_source == "mock" else "LIVE"
        self.ui.show_info(
            f"データソース: {source_label} | "
            f"ポーリング間隔: {self.config.poll_interval_sec}秒 | "
            f"シグナル条件: {self.config.signal_min_wallets}+ wallets / "
            f"{self.config.signal_time_window_sec}秒窓"
        )

        if self.notifier.is_enabled:
            self.ui.show_info("Discord通知: 有効")
        else:
            self.ui.show_info("Discord通知: 無効 (.envにDISCORD_WEBHOOK_URLを設定)")

        self._running = True
        cycle = 0

        while self._running:
            cycle += 1
            try:
                await self._run_cycle(cycle)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Cycle #%d でエラー発生", cycle)
                self.ui.show_error(f"Cycle #{cycle} エラー: {e}")

            # 次のポーリングまで待機
            try:
                self.ui.show_status(
                    cycle=cycle,
                    trade_count=await self.db.get_trade_count(),
                    signal_count=await self.db.get_signal_count(),
                    next_poll=self.config.poll_interval_sec,
                )
                await asyncio.sleep(self.config.poll_interval_sec)
            except asyncio.CancelledError:
                break

        await self._cleanup()

    async def _run_cycle(self, cycle: int) -> None:
        """1回のポーリングサイクルを実行する。"""
        all_trades = []

        for wallet in self.config.wallets:
            try:
                trades = await self.collector.fetch_recent_trades(wallet.address)
                all_trades.extend(trades)
            except Exception as e:
                logger.error(
                    "ウォレット %s のデータ取得に失敗: %s", wallet.label, e
                )
                self.ui.show_error(
                    f"ウォレット {wallet.label} の取得失敗（スキップ）: {e}"
                )

        # 正規化
        normalized = normalize_trades(all_trades)

        # 表示
        self.ui.show_trades(normalized, cycle)

        # DB保存
        if normalized:
            inserted = await self.db.insert_trades(normalized)
            logger.info("Cycle #%d: %d件の取引を保存", cycle, inserted)

        # シグナル検知
        signals = self.detector.ingest(normalized)
        self.ui.show_signals(signals)

        # シグナルをDB保存 & Discord通知
        for sig in signals:
            try:
                await self.db.insert_signal(sig)
            except Exception as e:
                logger.error("シグナルのDB保存に失敗: %s", e)

            if self.notifier.is_enabled:
                try:
                    await self.notifier.send_signal(sig)
                except Exception as e:
                    logger.error("Discord通知の送信に失敗: %s", e)

    async def _cleanup(self) -> None:
        """リソースのクリーンアップ。"""
        self.ui.show_info("シャットダウン中...")
        await self.collector.close()
        await self.notifier.close()
        await self.db.close()
        self.ui.show_info("正常にシャットダウンしました。")

    def stop(self) -> None:
        self._running = False


def main() -> None:
    config = Config.from_env()
    config.setup_logging()
    config.load_wallets()

    tracker = WalletTracker(config)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def handle_signal(sig, frame):
        tracker.stop()

    signal.signal(signal.SIGINT, handle_signal)
    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, handle_signal)

    try:
        loop.run_until_complete(tracker.start())
    except KeyboardInterrupt:
        tracker.stop()
        loop.run_until_complete(tracker._cleanup())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
