"""Main entry point for the Polymarket arbitrage monitoring bot."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from datetime import datetime
from pathlib import Path

# Add parent dir to path for direct execution
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_config
from src.logger import setup_logger
from src.market_discovery import MarketDiscovery
from src.metrics import MetricsCollector
from src.models import Market, OrderBookSnapshot
from src.notifier import Notifier
from src.paper_trader import PaperTrader
from src.signal_engine import SignalEngine
from src.websocket_client import PolymarketWebSocket


class Bot:
    """Main bot orchestrator."""

    def __init__(self) -> None:
        self.config = load_config()
        self.logger = setup_logger(
            level=self.config.log_level,
            log_file=self.config.log_file,
        )
        self.discovery = MarketDiscovery(self.config)
        self.signal_engine = SignalEngine(self.config)
        self.paper_trader = PaperTrader(self.config)
        self.metrics = MetricsCollector(
            data_dir=str(Path(__file__).resolve().parent.parent / "data")
        )
        self.notifier = Notifier(self.config)
        self.ws_client: PolymarketWebSocket | None = None

        # Track active markets by condition_id
        self._markets: dict[str, Market] = {}
        # Map token_id -> condition_id for WS updates
        self._token_to_market: dict[str, str] = {}
        self._running = False

    async def start(self) -> None:
        """Start the bot."""
        self.logger.info("=" * 50)
        self.logger.info("Polymarket Arbitrage Bot starting (PAPER MODE)")
        self.logger.info("=" * 50)
        self._running = True

        # Setup graceful shutdown
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))
            except NotImplementedError:
                # Windows doesn't support add_signal_handler
                pass

        try:
            # Initial market discovery
            await self._discover_markets()

            if not self._markets:
                self.logger.warning("No BTC short-term markets found. Will keep polling...")

            # Start WS and polling concurrently
            await asyncio.gather(
                self._run_ws(),
                self._run_poll_loop(),
                self._run_exit_checker(),
                return_exceptions=True,
            )
        except asyncio.CancelledError:
            pass
        finally:
            await self._cleanup()

    async def shutdown(self) -> None:
        """Graceful shutdown."""
        self.logger.info("Shutting down...")
        self._running = False

        # Close all open positions
        for market in self._markets.values():
            closed = self.paper_trader.close_all(market)
            self.metrics.record_positions(closed)

        # Generate final summary
        summary = self.metrics.generate_daily_summary()
        self.metrics.print_summary(summary)
        self.metrics.save_summary_json(summary)
        self.metrics.save_trades_csv()

    async def _cleanup(self) -> None:
        if self.ws_client:
            await self.ws_client.stop()
        await self.discovery.close()

    async def _discover_markets(self) -> None:
        """Discover BTC short-term markets."""
        self.logger.info("Discovering BTC short-term markets...")
        markets = await self.discovery.fetch_all_btc_short_term_markets()

        for market in markets:
            self._markets[market.condition_id] = market
            # Enrich with order books
            await self.discovery.enrich_market_with_books(market)
            # Map tokens
            for token in market.tokens:
                self._token_to_market[token.token_id] = market.condition_id
                # Seed price history
                if token.order_book.best_bid is not None:
                    mid = token.order_book.best_bid
                    if token.order_book.best_ask is not None:
                        mid = (token.order_book.best_bid + token.order_book.best_ask) / 2
                    self.signal_engine.record_price(token.token_id, mid)

        self.logger.info("Tracking %d markets with %d tokens",
                         len(self._markets), len(self._token_to_market))

    async def _run_ws(self) -> None:
        """Run WebSocket client for live book updates."""
        if not self._token_to_market:
            self.logger.info("No tokens to subscribe, skipping WebSocket")
            return

        self.ws_client = PolymarketWebSocket(
            self.config,
            on_book_update=self._on_book_update,
        )

        # Subscribe to all tracked tokens
        await self.ws_client.subscribe(list(self._token_to_market.keys()))

        # Connect (blocks until stopped or max reconnects)
        await self.ws_client.connect()

    def _on_book_update(self, token_id: str, book: OrderBookSnapshot) -> None:
        """Handle a real-time book update from WebSocket."""
        condition_id = self._token_to_market.get(token_id)
        if not condition_id:
            return

        market = self._markets.get(condition_id)
        if not market:
            return

        # Update the correct token's order book
        for token in market.tokens:
            if token.token_id == token_id:
                token.order_book = book
                # Record price for momentum
                if book.best_bid is not None and book.best_ask is not None:
                    mid = (book.best_bid + book.best_ask) / 2
                    self.signal_engine.record_price(token_id, mid)
                break

        market.last_updated = datetime.utcnow()

        # Evaluate signals synchronously (fast enough)
        self._evaluate_market(market)

    async def _run_poll_loop(self) -> None:
        """Periodically rediscover markets and refresh order books."""
        while self._running:
            await asyncio.sleep(self.config.poll_interval_sec)
            if not self._running:
                break

            try:
                # Refresh market list periodically
                await self._discover_markets()

                # Subscribe new tokens if any
                if self.ws_client and self._token_to_market:
                    await self.ws_client.subscribe(list(self._token_to_market.keys()))

                # Evaluate all markets (in case WS missed updates)
                for market in list(self._markets.values()):
                    await self.discovery.enrich_market_with_books(market)
                    self._evaluate_market(market)

            except Exception as e:
                self.logger.error("Error in poll loop: %s", e)

    async def _run_exit_checker(self) -> None:
        """Periodically check open positions for TP/SL/timeout."""
        while self._running:
            await asyncio.sleep(1)
            if not self._running:
                break

            for market in list(self._markets.values()):
                try:
                    closed = self.paper_trader.check_exits(market)
                    if closed:
                        self.metrics.record_positions(closed)
                except Exception as e:
                    self.logger.error("Error checking exits: %s", e)

    def _evaluate_market(self, market: Market) -> None:
        """Evaluate a market for signals and potentially enter a trade."""
        try:
            result = self.signal_engine.evaluate(market)
            if result is None:
                return

            if result.confidence_score >= self.config.confidence_threshold:
                # Notify
                asyncio.ensure_future(self.notifier.notify(result))

                # Enter paper trade if we can
                if self.paper_trader.can_open():
                    position = self.paper_trader.enter(result)
                    if position:
                        self.metrics.record_position(position)

        except Exception as e:
            self.logger.error("Error evaluating market %s: %s",
                              market.condition_id[:8], e)


async def main() -> None:
    bot = Bot()
    try:
        await bot.start()
    except KeyboardInterrupt:
        await bot.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped by user.")
