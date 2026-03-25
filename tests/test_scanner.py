"""scanner.py のテスト"""

import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "flow_bot"))

import config
from scanner import _passes_filters, _calc_dte, _to_option_flow, scan_ticker


def _make_snapshot(**overrides):
    """テスト用スナップショットデータを生成"""
    snap = {
        "details": {
            "contract_type": "call",
            "expiration_date": "2026-04-10",
            "strike_price": 200.0,
            "ticker": "O:AAPL260410C00200000",
        },
        "day": {
            "volume": 5000,
            "close": 3.50,
        },
        "open_interest": 500,
        "last_quote": {
            "midpoint": 3.50,
        },
    }
    # Apply overrides with nested merge
    for key, value in overrides.items():
        if isinstance(value, dict) and key in snap:
            snap[key].update(value)
        else:
            snap[key] = value
    return snap


class TestPassesFilters:
    def test_valid_flow_passes(self):
        """条件を満たすフローはTrue"""
        snap = _make_snapshot()
        assert _passes_filters(snap) is True

    def test_put_rejected(self):
        """PUTは除外"""
        snap = _make_snapshot(details={"contract_type": "put", "expiration_date": "2026-04-10", "strike_price": 200.0, "ticker": "X"})
        assert _passes_filters(snap) is False

    def test_low_volume_oi_rejected(self):
        """Vol/OI比 < 5 は除外"""
        snap = _make_snapshot(open_interest=5000)  # 5000/5000 = 1.0
        assert _passes_filters(snap) is False

    def test_low_premium_rejected(self):
        """プレミアム < $100k は除外"""
        snap = _make_snapshot(**{"day": {"volume": 100, "close": 1.0}, "last_quote": {"midpoint": 1.0}})
        assert _passes_filters(snap) is False

    def test_zero_oi_rejected(self):
        """OI = 0 は除外"""
        snap = _make_snapshot(open_interest=0)
        assert _passes_filters(snap) is False


class TestCalcDte:
    def test_future_date(self):
        """未来の日付は正のDTE"""
        dte = _calc_dte("2099-12-31")
        assert dte > 0

    def test_past_date(self):
        """過去の日付は負のDTE"""
        dte = _calc_dte("2020-01-01")
        assert dte < 0


class TestToOptionFlow:
    def test_conversion(self):
        """スナップショットからOptionFlowへの変換"""
        snap = _make_snapshot()
        flow = _to_option_flow(snap, "AAPL")
        assert flow.ticker == "AAPL"
        assert flow.strike == 200.0
        assert flow.side == "call"
        assert flow.volume == 5000
        assert flow.open_interest == 500
        assert flow.volume_oi_ratio == 10.0
        assert flow.premium == 5000 * 3.50 * 100


class TestScanTicker:
    @patch("scanner.requests.get")
    def test_api_error_returns_empty(self, mock_get):
        """API失敗時は空リストを返す"""
        import requests as req
        mock_get.side_effect = req.ConnectionError("Network error")
        result = scan_ticker("AAPL")
        assert result == []

    @patch("scanner.requests.get")
    def test_no_results(self, mock_get):
        """結果なしの場合は空リスト"""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": []}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp
        result = scan_ticker("AAPL")
        assert result == []
