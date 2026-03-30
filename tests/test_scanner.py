"""scanner.py のテスト"""

import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "flow_bot"))

import config
from scanner import OptionFlow, _calc_dte, scan_ticker


class TestCalcDte:
    def test_future_date(self):
        """未来の日付は正のDTE"""
        dte = _calc_dte("2099-12-31")
        assert dte > 0

    def test_past_date(self):
        """過去の日付は負のDTE"""
        dte = _calc_dte("2020-01-01")
        assert dte < 0


class TestScanTicker:
    @patch("scanner.requests.get")
    def test_api_error_returns_empty(self, mock_get):
        """API失敗時は空リストを返す"""
        import requests as req
        mock_get.side_effect = req.ConnectionError("Network error")
        result = scan_ticker("AAPL")
        assert result == []

    @patch("scanner._api_get")
    def test_no_contracts(self, mock_api):
        """契約なしの場合は空リスト"""
        mock_api.return_value = {"results": []}
        result = scan_ticker("AAPL")
        assert result == []

    @patch("scanner._api_get")
    def test_detects_unusual_flow(self, mock_api):
        """条件を満たすフローが検出される"""
        from datetime import datetime, timedelta
        exp = (datetime.now() + timedelta(days=15)).strftime("%Y-%m-%d")
        contracts_resp = {"results": [{
            "ticker": "O:AAPL260410C00200000",
            "expiration_date": exp,
            "strike_price": 200.0,
            "contract_type": "call",
            "open_interest": 500,
        }]}
        bar_resp = {"results": [{
            "v": 5000,
            "c": 3.50,
        }]}

        mock_api.side_effect = [contracts_resp, bar_resp]
        result = scan_ticker("AAPL")
        assert len(result) == 1
        assert result[0].ticker == "AAPL"
        assert result[0].volume == 5000
        assert result[0].volume_oi_ratio == 10.0
        assert result[0].premium == 5000 * 3.50 * 100

    @patch("scanner._api_get")
    def test_filters_low_vol_oi(self, mock_api):
        """Vol/OI比が低い場合は除外"""
        from datetime import datetime, timedelta
        exp = (datetime.now() + timedelta(days=15)).strftime("%Y-%m-%d")
        contracts_resp = {"results": [{
            "ticker": "O:AAPL260410C00200000",
            "expiration_date": exp,
            "strike_price": 200.0,
            "contract_type": "call",
            "open_interest": 5000,
        }]}
        bar_resp = {"results": [{
            "v": 100,  # vol/oi = 0.02
            "c": 3.50,
        }]}

        mock_api.side_effect = [contracts_resp, bar_resp]
        result = scan_ticker("AAPL")
        assert result == []
