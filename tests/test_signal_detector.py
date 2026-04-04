"""シグナル検知のテスト。"""

from datetime import datetime, timezone

from src.collector.base import Trade
from src.processor.signal_detector import SignalDetector


def _make_trade(wallet: str, market: str = "m1", side: str = "buy",
                outcome: str = "Yes", amount: float = 100.0,
                ts: datetime | None = None) -> Trade:
    return Trade(
        tx_hash=f"0x_{wallet}_{market}",
        wallet_address=wallet,
        market_id=market,
        market_title="Test Market",
        outcome=outcome,
        side=side,
        amount_usdc=amount,
        price=0.65,
        timestamp=ts or datetime.now(timezone.utc),
    )


def test_no_signal_below_threshold():
    detector = SignalDetector(time_window_sec=300, min_wallets=3)
    trades = [
        _make_trade("wallet_a"),
        _make_trade("wallet_b"),
    ]
    signals = detector.ingest(trades)
    assert len(signals) == 0


def test_signal_when_enough_wallets():
    detector = SignalDetector(time_window_sec=300, min_wallets=3)
    trades = [
        _make_trade("wallet_a"),
        _make_trade("wallet_b"),
        _make_trade("wallet_c"),
    ]
    signals = detector.ingest(trades)
    assert len(signals) == 1
    assert signals[0].wallet_count == 3
    assert signals[0].direction == "Buy-Yes"


def test_strong_signal():
    detector = SignalDetector(
        time_window_sec=300, min_wallets=3, strong_amount_threshold=500.0
    )
    trades = [
        _make_trade("wallet_a", amount=200.0),
        _make_trade("wallet_b", amount=200.0),
        _make_trade("wallet_c", amount=200.0),
    ]
    signals = detector.ingest(trades)
    assert len(signals) == 1
    assert signals[0].is_strong is True
    assert signals[0].total_amount_usdc == 600.0


def test_different_directions_separate():
    detector = SignalDetector(time_window_sec=300, min_wallets=2)
    trades = [
        _make_trade("wallet_a", side="buy", outcome="Yes"),
        _make_trade("wallet_b", side="sell", outcome="Yes"),
        _make_trade("wallet_c", side="buy", outcome="Yes"),
    ]
    signals = detector.ingest(trades)
    # Buy-Yesが2ウォレット、Sell-Yesが1ウォレット → Buy-Yesのみシグナル
    buy_signals = [s for s in signals if s.direction == "Buy-Yes"]
    sell_signals = [s for s in signals if s.direction == "Sell-Yes"]
    assert len(buy_signals) == 1
    assert len(sell_signals) == 0


def test_clear_resets_buffer():
    detector = SignalDetector(time_window_sec=300, min_wallets=2)
    trades = [_make_trade("wallet_a"), _make_trade("wallet_b")]
    detector.ingest(trades)
    detector.clear()
    signals = detector.ingest([_make_trade("wallet_c")])
    assert len(signals) == 0
