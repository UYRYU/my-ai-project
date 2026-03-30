"""Bybit USDT無期限先物 APIクライアント"""

import hashlib
import hmac
import time
import json
import requests
from urllib.parse import urlencode

BASE_URL = "https://api.bybit.com"


class BybitClient:
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.session = requests.Session()
        self.recv_window = "5000"

    def _sign(self, params: str, timestamp: str) -> str:
        payload = f"{timestamp}{self.api_key}{self.recv_window}{params}"
        return hmac.new(
            self.api_secret.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()

    def _headers(self, params_str: str) -> dict:
        timestamp = str(int(time.time() * 1000))
        signature = self._sign(params_str, timestamp)
        return {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-SIGN": signature,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-RECV-WINDOW": self.recv_window,
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: dict | None = None) -> dict:
        params = params or {}
        qs = urlencode(sorted(params.items()))
        headers = self._headers(qs)
        url = f"{BASE_URL}{path}"
        if qs:
            url += "?" + qs
        resp = self.session.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("retCode") != 0:
            raise ValueError(f"API error: {data.get('retMsg')} ({data.get('retCode')})")
        return data

    def _post(self, path: str, data: dict | None = None) -> dict:
        data = data or {}
        body = json.dumps(data)
        headers = self._headers(body)
        resp = self.session.post(f"{BASE_URL}{path}", data=body, headers=headers, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        if result.get("retCode") != 0:
            raise ValueError(f"API error: {result.get('retMsg')} ({result.get('retCode')})")
        return result

    # === 公開API (認証不要) ===

    def get_ticker(self, symbol: str) -> dict:
        resp = self.session.get(
            f"{BASE_URL}/v5/market/tickers",
            params={"category": "linear", "symbol": symbol},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("result", {}).get("list", [])
        if not items:
            raise ValueError(f"ティッカー取得失敗: {symbol}")
        return items[0]

    def get_klines(self, symbol: str, interval: str = "15", limit: int = 100) -> list:
        resp = self.session.get(
            f"{BASE_URL}/v5/market/kline",
            params={"category": "linear", "symbol": symbol, "interval": interval, "limit": limit},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        klines = data.get("result", {}).get("list", [])
        # Bybitは新しい順なので逆転、[startTime, open, high, low, close, volume, turnover]
        return [
            {"time": int(k[0]) // 1000, "open": float(k[1]), "high": float(k[2]),
             "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])}
            for k in reversed(klines)
        ]

    def get_orderbook(self, symbol: str, limit: int = 5) -> dict:
        resp = self.session.get(
            f"{BASE_URL}/v5/market/orderbook",
            params={"category": "linear", "symbol": symbol, "limit": limit},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("result", {})

    # === 認証API ===

    def set_leverage(self, symbol: str, leverage: int):
        return self._post("/v5/position/set-leverage", {
            "category": "linear",
            "symbol": symbol,
            "buyLeverage": str(leverage),
            "sellLeverage": str(leverage),
        })

    def set_margin_mode(self, symbol: str, mode: int = 0):
        """mode: 0=cross, 1=isolated"""
        return self._post("/v5/position/switch-isolated", {
            "category": "linear",
            "symbol": symbol,
            "tradeMode": mode,
            "buyLeverage": "5",
            "sellLeverage": "5",
        })

    def get_positions(self, symbol: str | None = None) -> list:
        params = {"category": "linear", "settleCoin": "USDT"}
        if symbol:
            params["symbol"] = symbol
        data = self._get("/v5/position/list", params)
        return data.get("result", {}).get("list", [])

    def get_wallet_balance(self) -> dict:
        data = self._get("/v5/account/wallet-balance", {"accountType": "UNIFIED"})
        return data.get("result", {})

    def place_order(
        self,
        symbol: str,
        side: str,
        qty: str,
        order_type: str = "Market",
        price: str | None = None,
        take_profit: str | None = None,
        stop_loss: str | None = None,
        reduce_only: bool = False,
    ) -> dict:
        data = {
            "category": "linear",
            "symbol": symbol,
            "side": side,      # "Buy" or "Sell"
            "orderType": order_type,
            "qty": qty,
            "timeInForce": "GTC" if order_type == "Limit" else "IOC",
        }
        if price:
            data["price"] = price
        if take_profit:
            data["takeProfit"] = take_profit
        if stop_loss:
            data["stopLoss"] = stop_loss
        if reduce_only:
            data["reduceOnly"] = True
        return self._post("/v5/order/create", data)

    def cancel_all_orders(self, symbol: str) -> dict:
        return self._post("/v5/order/cancel-all", {
            "category": "linear",
            "symbol": symbol,
        })

    def get_open_orders(self, symbol: str) -> list:
        data = self._get("/v5/order/realtime", {
            "category": "linear",
            "symbol": symbol,
        })
        return data.get("result", {}).get("list", [])

    def get_instrument_info(self, symbol: str) -> dict:
        resp = self.session.get(
            f"{BASE_URL}/v5/market/instruments-info",
            params={"category": "linear", "symbol": symbol},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("result", {}).get("list", [])
        if not items:
            raise ValueError(f"銘柄情報取得失敗: {symbol}")
        return items[0]
