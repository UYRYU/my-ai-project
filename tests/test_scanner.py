"""scanner.py のテスト"""

import sys
import os
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "flow_bot"))

from scanner import OptionFlow, _calc_dte, _parse_contract_symbol, scan_ticker


class TestCalcDte:
    def test_future_date(self):
        dte = _calc_dte("2099-12-31")
        assert dte > 0

    def test_past_date(self):
        dte = _calc_dte("2020-01-01")
        assert dte < 0


class TestParseContractSymbol:
    def test_standard_call(self):
        result = _parse_contract_symbol("AAPL260410C00200000")
        assert result["underlying"] == "AAPL"
        assert result["expiration"] == "2026-04-10"
        assert result["strike"] == 200.0
        assert result["side"] == "call"

    def test_standard_put(self):
        result = _parse_contract_symbol("TSLA260401P00150000")
        assert result["side"] == "put"

    def test_invalid_short(self):
        result = _parse_contract_symbol("X")
        assert result is None


class TestScanTicker:
    @patch("scanner.requests.get")
    def test_api_error_returns_empty(self, mock_get):
        import requests as req
        mock_get.side_effect = req.ConnectionError("Network error")
        result = scan_ticker("AAPL")
        assert result == []

    @patch("scanner._get_option_snapshots")
    def test_no_snapshots(self, mock_snap):
        mock_snap.return_value = {}
        result = scan_ticker("AAPL")
        assert result == []

    @patch("scanner._get_option_snapshots")
    def test_detects_unusual_flow(self, mock_snap):
        exp = (datetime.now() + timedelta(days=15)).strftime("%y%m%d")
        symbol = f"AAPL{exp}C00200000"
        mock_snap.return_value = {
            symbol: {
                "dayVolume": 5000,
                "openInterest": 500,
                "latestTrade": {"p": 3.50},
                "latestQuote": {"bp": 3.40, "ap": 3.60},
            }
        }
        result = scan_ticker("AAPL")
        assert len(result) == 1
        assert result[0].ticker == "AAPL"
        assert result[0].volume == 5000
        assert result[0].volume_oi_ratio == 10.0
        assert result[0].premium == 5000 * 3.50 * 100

    @patch("scanner._get_option_snapshots")
    def test_filters_low_vol_oi(self, mock_snap):
        exp = (datetime.now() + timedelta(days=15)).strftime("%y%m%d")
        symbol = f"AAPL{exp}C00200000"
        mock_snap.return_value = {
            symbol: {
                "dayVolume": 100,
                "openInterest": 5000,  # vol/oi = 0.02
                "latestTrade": {"p": 3.50},
                "latestQuote": {},
            }
        }
        result = scan_ticker("AAPL")
        assert result == []
