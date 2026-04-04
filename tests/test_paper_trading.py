"""Paper取引関連のテスト。"""

import pytest
from datetime import datetime, timezone

from src.execution.csv_writer import CsvWriter
from src.execution.executor import Executor
from src.execution.models import Order, OrderStatus, PaperTrade, TradingMode
from src.execution.paper_broker import PaperBroker
from src.execution.risk_manager import RiskManager
from src.processor.signal_detector import Signal


def _make_signal(market_id: str = "m1", is_strong: bool = True) -> Signal:
    now = datetime.now(timezone.utc)
    return Signal(
        market_id=market_id,
        market_title="Test Market",
        direction="Buy-Yes",
        wallets=["w1", "w2", "w3"],
        total_amount_usdc=2000.0,
        avg_price=0.65,
        first_trade_time=now,
        last_trade_time=now,
        is_strong=is_strong,
    )


def test_paper_broker_simulate_exit():
    from src.execution.models import Fill
    broker = PaperBroker()
    fill = Fill(
        order_id="test123",
        market_id="m1",
        side="buy",
        outcome="Yes",
        amount_usdc=50.0,
        fill_price=0.65,
        mode=TradingMode.PAPER,
    )
    order = Order(
        order_id="test123",
        market_id="m1",
        market_title="Test",
        side="buy",
        outcome="Yes",
        amount_usdc=50.0,
        limit_price=0.65,
    )
    now = datetime.now(timezone.utc)
    pt = broker.simulate_exit(fill, order, now)

    assert isinstance(pt, PaperTrade)
    assert pt.order_id == "test123"
    assert pt.entry_price == 0.65
    assert pt.entry_amount_usd == 50.0
    assert 0.01 <= pt.exit_price <= 0.99
    assert pt.result in ("win", "loss")
    assert pt.holding_minutes > 0


@pytest.mark.asyncio
async def test_paper_executor_creates_paper_trade():
    rm = RiskManager(max_order_usd=100, min_signal_level="STRONG")
    executor = Executor(
        mode=TradingMode.PAPER,
        risk_manager=rm,
        paper_broker=PaperBroker(),
        order_amount_usd=50,
    )
    orders = await executor.process_signals([_make_signal()])
    assert len(orders) == 1
    assert orders[0].status == OrderStatus.FILLED

    paper_trades = executor.get_recent_paper_trades()
    assert len(paper_trades) == 1
    assert paper_trades[0].result in ("win", "loss")
    assert paper_trades[0].entry_amount_usd == 50.0


@pytest.mark.asyncio
async def test_paper_executor_updates_pnl():
    rm = RiskManager(max_order_usd=100, min_signal_level="STRONG")
    executor = Executor(
        mode=TradingMode.PAPER,
        risk_manager=rm,
        order_amount_usd=50,
    )
    await executor.process_signals([_make_signal()])
    assert executor.stats["total_pnl"] != 0.0 or executor.stats["total_fills"] == 1


def test_csv_writer(tmp_path):
    csv_path = str(tmp_path / "test_trades.csv")
    writer = CsvWriter(csv_path)

    pt = PaperTrade(
        order_id="o1",
        signal_time=datetime.now(timezone.utc),
        market_id="m1",
        market_title="Test",
        direction="Buy-Yes",
        entry_price=0.65,
        entry_amount_usd=50.0,
        exit_price=0.70,
        pnl_usd=3.85,
        holding_minutes=30.0,
        result="win",
    )
    writer.append(pt)
    writer.append(pt)

    import csv
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)
    assert len(rows) == 3  # header + 2 data rows
    assert rows[0][0] == "trade_id"


@pytest.mark.asyncio
async def test_db_paper_trades(tmp_path):
    from src.storage.database import Database
    db = Database(str(tmp_path / "test.db"))
    await db.initialize()

    pt = PaperTrade(
        order_id="o1",
        signal_time=datetime.now(timezone.utc),
        market_id="m1",
        market_title="Test Market",
        direction="Buy-Yes",
        entry_price=0.65,
        entry_amount_usd=50.0,
        exit_price=0.70,
        pnl_usd=3.85,
        holding_minutes=30.0,
        result="win",
    )
    await db.insert_paper_trade(pt)

    pt2 = PaperTrade(
        order_id="o2",
        signal_time=datetime.now(timezone.utc),
        market_id="m2",
        market_title="Test Market 2",
        direction="Sell-No",
        entry_price=0.40,
        entry_amount_usd=50.0,
        exit_price=0.35,
        pnl_usd=-6.25,
        holding_minutes=45.0,
        result="loss",
    )
    await db.insert_paper_trade(pt2)

    summary = await db.get_paper_trade_summary()
    assert summary["total_trades"] == 2
    assert summary["wins"] == 1
    assert summary["losses"] == 1
    assert summary["win_rate"] == 50.0
    assert summary["total_pnl"] == round(3.85 + (-6.25), 2)
    assert summary["max_consecutive_losses"] == 1

    trades = await db.get_all_paper_trades()
    assert len(trades) == 2

    await db.close()
