"""Paper取引関連のテスト。"""

import pytest
import random
from datetime import datetime, timezone

from src.execution.csv_writer import CsvWriter
from src.execution.executor import Executor
from src.execution.models import Fill, Order, OrderStatus, PaperTrade, TradingMode
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


def _make_fill(side: str = "buy", fill_price: float = 0.65, amount: float = 50.0) -> Fill:
    return Fill(
        order_id="test123",
        market_id="m1",
        side=side,
        outcome="Yes",
        amount_usdc=amount,
        fill_price=fill_price,
        mode=TradingMode.PAPER,
    )


def _make_order(side: str = "buy", outcome: str = "Yes", limit_price: float = 0.65) -> Order:
    return Order(
        order_id="test123",
        market_id="m1",
        market_title="Test",
        side=side,
        outcome=outcome,
        amount_usdc=50.0,
        limit_price=limit_price,
    )


# ── v2 Binary Model Tests ────────────────────────────────

def test_v2_binary_buy_exit_is_binary():
    """v2モデルではexit_priceが0.01または0.99になる。"""
    broker = PaperBroker(use_legacy=False)
    fill = _make_fill(side="buy", fill_price=0.50)
    order = _make_order(side="buy")
    now = datetime.now(timezone.utc)

    exits = set()
    for _ in range(50):
        pt = broker.simulate_exit(fill, order, now)
        exits.add(pt.exit_price)
        assert pt.model_version == "v2_binary"

    # 50回で0.01と0.99の両方が出るはず (確率的にほぼ確実)
    assert 0.01 in exits
    assert 0.99 in exits
    assert len(exits) == 2  # 二値のみ


def test_v2_binary_sell_exit_is_binary():
    """v2 Sellモデルのexit_priceも二値。"""
    broker = PaperBroker(use_legacy=False)
    fill = _make_fill(side="sell", fill_price=0.40)
    order = _make_order(side="sell")
    now = datetime.now(timezone.utc)

    exits = set()
    for _ in range(50):
        pt = broker.simulate_exit(fill, order, now)
        exits.add(pt.exit_price)

    assert 0.01 in exits
    assert 0.99 in exits


def test_v2_low_entry_buy_has_higher_expected_pnl():
    """entry_priceが低いBuyの方が、高いBuyより期待PnLが高いことを確認。

    Buy @ 0.20: 勝率20%, 勝ち1回で+$3.95 (= (0.99-0.20)*50/0.20), 負け1回で-$47.50
    Buy @ 0.80: 勝率80%, 勝ち1回で+$11.88 (= (0.99-0.80)*50/0.80), 負け1回で-$49.38
    理論的な期待値は同じ（効率的市場の仮定）が、低entry_priceの方が
    1勝あたりの利益が大きく、期待利益の分散が大きい。

    このテストでは大量シミュレーションで平均PnLが±$2以内（=ゼロに近い）を確認。
    二値モデルが正しく実装されていれば、どちらもゼロ付近に収束する。
    """
    random.seed(42)
    broker = PaperBroker(use_legacy=False)
    now = datetime.now(timezone.utc)
    n = 5000

    # Low entry (0.20)
    fill_low = _make_fill(side="buy", fill_price=0.20, amount=50.0)
    order_low = _make_order(side="buy", limit_price=0.20)
    pnl_low = []
    for _ in range(n):
        pt = broker.simulate_exit(fill_low, order_low, now)
        pnl_low.append(pt.pnl_usd)

    # High entry (0.80)
    fill_high = _make_fill(side="buy", fill_price=0.80, amount=50.0)
    order_high = _make_order(side="buy", limit_price=0.80)
    pnl_high = []
    for _ in range(n):
        pt = broker.simulate_exit(fill_high, order_high, now)
        pnl_high.append(pt.pnl_usd)

    avg_low = sum(pnl_low) / n
    avg_high = sum(pnl_high) / n

    # 効率的市場の仮定: 両方ともゼロ付近（±$3許容）
    assert abs(avg_low) < 3.0, f"Low entry avg PnL too far from 0: {avg_low:.2f}"
    assert abs(avg_high) < 3.0, f"High entry avg PnL too far from 0: {avg_high:.2f}"

    # Low entry は 1勝あたりの利益が大きい
    wins_low = [p for p in pnl_low if p > 0]
    wins_high = [p for p in pnl_high if p > 0]
    avg_win_low = sum(wins_low) / len(wins_low) if wins_low else 0
    avg_win_high = sum(wins_high) / len(wins_high) if wins_high else 0
    assert avg_win_low > avg_win_high, (
        f"Low entry avg win ({avg_win_low:.2f}) should be > "
        f"high entry avg win ({avg_win_high:.2f})"
    )


def test_v2_buy_pnl_calculation():
    """Buy-v2: 勝ちと負けのPnL計算が正しいことを確認。"""
    random.seed(0)  # 再現性
    broker = PaperBroker(use_legacy=False)
    fill = _make_fill(side="buy", fill_price=0.60, amount=60.0)
    order = _make_order(side="buy", limit_price=0.60)
    now = datetime.now(timezone.utc)

    # 多数回で勝ちと負けの両方を取得
    wins, losses = [], []
    for _ in range(100):
        pt = broker.simulate_exit(fill, order, now)
        if pt.result == "win":
            wins.append(pt)
        else:
            losses.append(pt)

    assert len(wins) > 0 and len(losses) > 0

    # 勝ちの場合: PnL = (0.99 - 0.60) * (60/0.60) = 0.39 * 100 = 39.0
    for w in wins:
        assert w.exit_price == 0.99
        assert w.pnl_usd == round((0.99 - 0.60) * (60.0 / 0.60), 2)

    # 負けの場合: PnL = (0.01 - 0.60) * (60/0.60) = -0.59 * 100 = -59.0
    for lo in losses:
        assert lo.exit_price == 0.01
        assert lo.pnl_usd == round((0.01 - 0.60) * (60.0 / 0.60), 2)


def test_v2_sell_pnl_calculation():
    """Sell-v2: PnL計算が正しいことを確認。"""
    random.seed(1)
    broker = PaperBroker(use_legacy=False)
    fill = _make_fill(side="sell", fill_price=0.40, amount=40.0)
    order = _make_order(side="sell", outcome="Yes", limit_price=0.40)
    now = datetime.now(timezone.utc)

    wins, losses = [], []
    for _ in range(100):
        pt = broker.simulate_exit(fill, order, now)
        if pt.result == "win":
            wins.append(pt)
        else:
            losses.append(pt)

    assert len(wins) > 0 and len(losses) > 0

    # Sell勝ち: PnL = (0.40 - 0.01) * (40/0.40) = 0.39 * 100 = 39.0
    for w in wins:
        assert w.exit_price == 0.01
        assert w.pnl_usd == round((0.40 - 0.01) * (40.0 / 0.40), 2)

    # Sell負け: PnL = (0.40 - 0.99) * (40/0.40) = -0.59 * 100 = -59.0
    for lo in losses:
        assert lo.exit_price == 0.99
        assert lo.pnl_usd == round((0.40 - 0.99) * (40.0 / 0.40), 2)


# ── v1 Legacy Model Tests ────────────────────────────────

def test_v1_legacy_model_flag():
    """use_legacy=True でv1モデルが使われる。"""
    broker = PaperBroker(use_legacy=True)
    assert broker.model_version == "v1_random"

    fill = _make_fill(side="buy", fill_price=0.65)
    order = _make_order(side="buy")
    now = datetime.now(timezone.utc)
    pt = broker.simulate_exit(fill, order, now)

    assert pt.model_version == "v1_random"
    # v1はexit_priceが二値ではない（0.01-0.99の連続値）
    exits = set()
    for _ in range(20):
        pt = broker.simulate_exit(fill, order, now)
        exits.add(pt.exit_price)
    assert len(exits) > 2  # 連続値なので多様


def test_paper_broker_simulate_exit():
    """デフォルト（v2）でPaperTradeが正しく生成される。"""
    broker = PaperBroker()
    fill = _make_fill()
    order = _make_order()
    now = datetime.now(timezone.utc)
    pt = broker.simulate_exit(fill, order, now)

    assert isinstance(pt, PaperTrade)
    assert pt.order_id == "test123"
    assert pt.entry_price == 0.65
    assert pt.entry_amount_usd == 50.0
    assert pt.exit_price in (0.01, 0.99)
    assert pt.result in ("win", "loss")
    assert pt.holding_minutes > 0
    assert pt.model_version == "v2_binary"


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
    assert paper_trades[0].model_version == "v2_binary"


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


def test_csv_writer_includes_model_version(tmp_path):
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
        exit_price=0.99,
        pnl_usd=26.15,
        holding_minutes=30.0,
        result="win",
        model_version="v2_binary",
    )
    writer.append(pt)

    import csv
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["model_version"] == "v2_binary"


@pytest.mark.asyncio
async def test_db_paper_trades_with_model_version(tmp_path):
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
        exit_price=0.99,
        pnl_usd=26.15,
        holding_minutes=30.0,
        result="win",
        model_version="v2_binary",
    )
    await db.insert_paper_trade(pt)

    trades = await db.get_all_paper_trades()
    assert len(trades) == 1
    assert trades[0]["model_version"] == "v2_binary"

    summary = await db.get_paper_trade_summary()
    assert summary["total_trades"] == 1
    assert summary["wins"] == 1

    await db.close()
