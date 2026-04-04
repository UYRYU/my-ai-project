"""SQLiteデータベース管理モジュール。"""

import json
import logging

import aiosqlite

from src.collector.base import Trade
from src.processor.signal_detector import Signal

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str = "tracker.db"):
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS trades (
                tx_hash TEXT PRIMARY KEY,
                wallet_address TEXT NOT NULL,
                market_id TEXT NOT NULL,
                market_title TEXT,
                outcome TEXT,
                side TEXT,
                amount_usdc REAL,
                price REAL,
                timestamp TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_trades_wallet
                ON trades(wallet_address);
            CREATE INDEX IF NOT EXISTS idx_trades_market
                ON trades(market_id);
            CREATE INDEX IF NOT EXISTS idx_trades_timestamp
                ON trades(timestamp);

            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id TEXT NOT NULL,
                market_title TEXT,
                direction TEXT NOT NULL,
                wallet_count INTEGER,
                wallets_json TEXT,
                total_amount_usdc REAL,
                avg_price REAL,
                is_strong INTEGER DEFAULT 0,
                first_trade_time TEXT,
                last_trade_time TEXT,
                detected_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_signals_market
                ON signals(market_id);
            CREATE INDEX IF NOT EXISTS idx_signals_detected
                ON signals(detected_at);

            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                signal_market_id TEXT,
                signal_direction TEXT,
                market_id TEXT NOT NULL,
                market_title TEXT,
                side TEXT,
                outcome TEXT,
                amount_usdc REAL,
                limit_price REAL,
                status TEXT NOT NULL,
                mode TEXT NOT NULL,
                reject_reason TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_orders_market
                ON orders(market_id);
            CREATE INDEX IF NOT EXISTS idx_orders_status
                ON orders(status);

            CREATE TABLE IF NOT EXISTS fills (
                fill_id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                market_id TEXT NOT NULL,
                side TEXT,
                outcome TEXT,
                amount_usdc REAL,
                fill_price REAL,
                mode TEXT NOT NULL,
                filled_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (order_id) REFERENCES orders(order_id)
            );

            CREATE INDEX IF NOT EXISTS idx_fills_order
                ON fills(order_id);

            CREATE TABLE IF NOT EXISTS pnl (
                record_id TEXT PRIMARY KEY,
                market_id TEXT NOT NULL,
                side TEXT,
                outcome TEXT,
                entry_price REAL,
                amount_usdc REAL,
                realized_pnl REAL DEFAULT 0,
                mode TEXT NOT NULL,
                recorded_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        logger.info("データベース初期化完了: %s", self._db_path)

    async def insert_trades(self, trades: list[Trade]) -> int:
        if not self._db:
            raise RuntimeError("Database not initialized")

        inserted = 0
        for trade in trades:
            try:
                await self._db.execute(
                    """
                    INSERT OR IGNORE INTO trades
                    (tx_hash, wallet_address, market_id, market_title,
                     outcome, side, amount_usdc, price, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trade.tx_hash,
                        trade.wallet_address,
                        trade.market_id,
                        trade.market_title,
                        trade.outcome,
                        trade.side,
                        trade.amount_usdc,
                        trade.price,
                        trade.timestamp.isoformat(),
                    ),
                )
                inserted += 1
            except Exception as e:
                logger.warning("取引の挿入に失敗: %s - %s", trade.tx_hash, e)
        await self._db.commit()
        return inserted

    async def insert_order(self, order) -> None:
        """Order を保存する。"""
        if not self._db:
            raise RuntimeError("Database not initialized")
        await self._db.execute(
            """
            INSERT OR REPLACE INTO orders
            (order_id, signal_market_id, signal_direction, market_id,
             market_title, side, outcome, amount_usdc, limit_price,
             status, mode, reject_reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order.order_id,
                order.signal_market_id,
                order.signal_direction,
                order.market_id,
                order.market_title,
                order.side,
                order.outcome,
                order.amount_usdc,
                order.limit_price,
                order.status.value,
                order.mode.value,
                order.reject_reason,
                order.created_at.isoformat(),
            ),
        )
        await self._db.commit()

    async def insert_fill(self, fill) -> None:
        """Fill を保存する。"""
        if not self._db:
            raise RuntimeError("Database not initialized")
        await self._db.execute(
            """
            INSERT OR REPLACE INTO fills
            (fill_id, order_id, market_id, side, outcome,
             amount_usdc, fill_price, mode, filled_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fill.fill_id,
                fill.order_id,
                fill.market_id,
                fill.side,
                fill.outcome,
                fill.amount_usdc,
                fill.fill_price,
                fill.mode.value,
                fill.filled_at.isoformat(),
            ),
        )
        await self._db.commit()

    async def get_order_count(self) -> int:
        if not self._db:
            raise RuntimeError("Database not initialized")
        cursor = await self._db.execute("SELECT COUNT(*) FROM orders")
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_fill_count(self) -> int:
        if not self._db:
            raise RuntimeError("Database not initialized")
        cursor = await self._db.execute("SELECT COUNT(*) FROM fills")
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_total_pnl(self, mode: str = "paper") -> float:
        if not self._db:
            raise RuntimeError("Database not initialized")
        cursor = await self._db.execute(
            "SELECT COALESCE(SUM(realized_pnl), 0) FROM pnl WHERE mode = ?",
            (mode,),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0.0

    async def insert_signal(self, signal: Signal) -> None:
        if not self._db:
            raise RuntimeError("Database not initialized")

        await self._db.execute(
            """
            INSERT INTO signals
            (market_id, market_title, direction, wallet_count, wallets_json,
             total_amount_usdc, avg_price, is_strong,
             first_trade_time, last_trade_time, detected_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal.market_id,
                signal.market_title,
                signal.direction,
                signal.wallet_count,
                json.dumps(signal.wallets),
                signal.total_amount_usdc,
                signal.avg_price,
                1 if signal.is_strong else 0,
                signal.first_trade_time.isoformat(),
                signal.last_trade_time.isoformat(),
                signal.detected_at.isoformat(),
            ),
        )
        await self._db.commit()

    async def get_recent_trades(self, limit: int = 50) -> list[dict]:
        if not self._db:
            raise RuntimeError("Database not initialized")

        self._db.row_factory = aiosqlite.Row
        cursor = await self._db.execute(
            "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_trade_count(self) -> int:
        if not self._db:
            raise RuntimeError("Database not initialized")
        cursor = await self._db.execute("SELECT COUNT(*) FROM trades")
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_signal_count(self) -> int:
        if not self._db:
            raise RuntimeError("Database not initialized")
        cursor = await self._db.execute("SELECT COUNT(*) FROM signals")
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None
