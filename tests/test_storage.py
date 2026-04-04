"""ストレージのテスト。"""

import asyncio
from datetime import datetime, timezone

import pytest
import pytest_asyncio

from src.collector.base import Trade
from src.storage.database import Database


@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.initialize()
    yield database
    await database.close()


def _make_trade(tx_hash: str = "0x1") -> Trade:
    return Trade(
        tx_hash=tx_hash,
        wallet_address="0xabc",
        market_id="m1",
        market_title="Test",
        outcome="Yes",
        side="buy",
        amount_usdc=100.0,
        price=0.5,
        timestamp=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
    )


@pytest.mark.asyncio
async def test_insert_and_count(db):
    trades = [_make_trade("0x1"), _make_trade("0x2")]
    inserted = await db.insert_trades(trades)
    assert inserted == 2
    count = await db.get_trade_count()
    assert count == 2


@pytest.mark.asyncio
async def test_duplicate_ignored(db):
    await db.insert_trades([_make_trade("0x1")])
    await db.insert_trades([_make_trade("0x1")])
    count = await db.get_trade_count()
    assert count == 1


@pytest.mark.asyncio
async def test_get_recent_trades(db):
    await db.insert_trades([_make_trade("0x1"), _make_trade("0x2")])
    recent = await db.get_recent_trades(limit=10)
    assert len(recent) == 2
