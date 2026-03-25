"""classifier.py のテスト"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "flow_bot"))

from scanner import OptionFlow
from classifier import classify, format_alert, GOLDEN_SWEEP, STRONG, MODERATE


def _make_flow(**overrides) -> OptionFlow:
    """テスト用OptionFlowを生成"""
    defaults = {
        "ticker": "AAPL",
        "contract": "O:AAPL250425C00200000",
        "strike": 200.0,
        "expiration": "2025-04-25",
        "dte": 15,
        "volume": 10000,
        "open_interest": 500,
        "volume_oi_ratio": 20.0,
        "premium": 600000.0,
        "side": "call",
    }
    defaults.update(overrides)
    return OptionFlow(**defaults)


class TestClassify:
    def test_golden_sweep(self):
        """Vol/OI >= 10 かつ premium >= 500k → GOLDEN_SWEEP"""
        flow = _make_flow(volume_oi_ratio=12.0, premium=700_000)
        assert classify(flow) == GOLDEN_SWEEP

    def test_golden_sweep_boundary(self):
        """ちょうど閾値 → GOLDEN_SWEEP"""
        flow = _make_flow(volume_oi_ratio=10.0, premium=500_000)
        assert classify(flow) == GOLDEN_SWEEP

    def test_strong_high_vol_oi(self):
        """Vol/OI >= 8 だが premium < 500k → STRONG"""
        flow = _make_flow(volume_oi_ratio=9.0, premium=200_000)
        assert classify(flow) == STRONG

    def test_strong_high_premium(self):
        """Vol/OI < 8 だが premium >= 300k → STRONG"""
        flow = _make_flow(volume_oi_ratio=6.0, premium=400_000)
        assert classify(flow) == STRONG

    def test_moderate(self):
        """どちらの閾値にも達しない → MODERATE"""
        flow = _make_flow(volume_oi_ratio=5.5, premium=150_000)
        assert classify(flow) == MODERATE

    def test_golden_sweep_requires_both(self):
        """Vol/OI >= 10 でも premium < 500k → STRONG（GOLDEN_SWEEPにならない）"""
        flow = _make_flow(volume_oi_ratio=11.0, premium=200_000)
        assert classify(flow) == STRONG


class TestFormatAlert:
    def test_contains_ticker(self):
        flow = _make_flow(ticker="NVDA")
        result = format_alert(flow, STRONG)
        assert "NVDA" in result

    def test_contains_premium(self):
        flow = _make_flow(premium=250_000)
        result = format_alert(flow, MODERATE)
        assert "250.0K" in result

    def test_contains_level_text(self):
        flow = _make_flow()
        result = format_alert(flow, GOLDEN_SWEEP)
        assert "GOLDEN SWEEP" in result
