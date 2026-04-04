"""正規化処理のテスト。"""

from datetime import datetime, timezone

from src.collector.base import Trade
from src.processor.normalizer import normalize_trades


def _make_trade(tx_hash: str = "0x1", **kwargs) -> Trade:
    defaults = dict(
        tx_hash=tx_hash,
        wallet_address="0xABCDEF",
        market_id="m1",
        market_title="Test Market",
        outcome="yes",
        side="BUY",
        amount_usdc=100.0,
        price=0.5,
        timestamp=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    return Trade(**defaults)


def test_normalize_deduplicates():
    trades = [_make_trade("0x1"), _make_trade("0x1"), _make_trade("0x2")]
    result = normalize_trades(trades)
    assert len(result) == 2


def test_normalize_lowercases_address():
    trades = [_make_trade(wallet_address="0xABCDEF")]
    result = normalize_trades(trades)
    assert result[0].wallet_address == "0xabcdef"


def test_normalize_lowercases_side():
    trades = [_make_trade(side="BUY")]
    result = normalize_trades(trades)
    assert result[0].side == "buy"


def test_normalize_capitalizes_outcome():
    trades = [_make_trade(outcome="yes")]
    result = normalize_trades(trades)
    assert result[0].outcome == "Yes"


def test_normalize_sorts_by_timestamp():
    t1 = _make_trade("0x1", timestamp=datetime(2026, 1, 1, 12, 5, 0, tzinfo=timezone.utc))
    t2 = _make_trade("0x2", timestamp=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc))
    result = normalize_trades([t1, t2])
    assert result[0].tx_hash == "0x2"
    assert result[1].tx_hash == "0x1"
