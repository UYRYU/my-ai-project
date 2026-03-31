"""Bitget USDT-M先物 APIクライアント (API v2)"""

import base64
import hashlib
import hmac
import time
import json
import requests
from urllib.parse import urlencode

BASE_URL = "https://api.bitget.com"


class BitgetClient:
    def __init__(self, api_key: str, api_secret: str, passphrase: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.session = requests.Session()

    def _sign(self, timestamp: str, method: str, path: str, body: str = "") -> str:
        message = f"{timestamp}{method}{path}{body}"
        mac = hmac.new(
            self.api_secret.encode(), message.encode(), hashlib.sha256
        )
        return base64.b64encode(mac.digest()).decode()

    def _headers(self, method: str, path: str, body: str = "") -> dict:
        timestamp = str(int(time.time() * 1000))
        signature = self._sign(timestamp, method, path, body)
        return {
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
            "locale": "en-US",
        }

    def _get(self, path: str, params: dict | None = None) -> dict:
        params = params or {}
        qs = urlencode(sorted(params.items()))
        full_path = f"{path}?{qs}" if qs else path
        headers = self._headers("GET", full_path)
        url = f"{BASE_URL}{full_path}"
        resp = self.session.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != "00000":
            raise ValueError(f"API error: {data.get('msg')} ({data.get('code')})")
        return data

    def _post(self, path: str, data: dict | None = None) -> dict:
        data = data or {}
        body = json.dumps(data)
        headers = self._headers("POST", path, body)
        resp = self.session.post(f"{BASE_URL}{path}", data=body, headers=headers, timeout=10)
        try:
            result = resp.json()
        except Exception:
            resp.raise_for_status()
            raise
        if result.get("code") != "00000":
            raise ValueError(f"Bitget API: {result.get('msg')} (code:{result.get('code')})")
        return result

    # === 公開API ===

    def get_ticker(self, symbol: str) -> dict:
        """ティッカー取得 → Bybit互換形式で返す"""
        resp = self.session.get(
            f"{BASE_URL}/api/v2/mix/market/ticker",
            params={"productType": "USDT-FUTURES", "symbol": symbol},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data", [])
        if not items:
            raise ValueError(f"ティッカー取得失敗: {symbol}")
        t = items[0]
        return {"lastPrice": t.get("lastPr", "0")}

    def get_klines(self, symbol: str, interval: str = "15m", limit: int = 100) -> list:
        """K線取得"""
        # Bitgetの interval: 1m,5m,15m,30m,1H,4H,1D
        bg_interval = interval
        if interval.isdigit():
            bg_interval = f"{interval}m"

        resp = self.session.get(
            f"{BASE_URL}/api/v2/mix/market/candles",
            params={"productType": "USDT-FUTURES", "symbol": symbol,
                    "granularity": bg_interval, "limit": str(limit)},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        klines = data.get("data", [])
        # Bitget: [timestamp, open, high, low, close, volume, quoteVolume]
        # 新しい順なので逆転
        return [
            {"time": int(k[0]) // 1000, "open": float(k[1]), "high": float(k[2]),
             "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])}
            for k in reversed(klines)
        ]

    def get_orderbook(self, symbol: str, limit: int = 5) -> dict:
        resp = self.session.get(
            f"{BASE_URL}/api/v2/mix/market/merge-depth",
            params={"productType": "USDT-FUTURES", "symbol": symbol, "limit": str(limit)},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        result = data.get("data", {})
        # Bybit互換: "b" = bids, "a" = asks
        return {"b": result.get("bids", []), "a": result.get("asks", [])}

    # === 認証API ===

    def set_leverage(self, symbol: str, leverage: int):
        return self._post("/api/v2/mix/account/set-leverage", {
            "symbol": symbol,
            "productType": "USDT-FUTURES",
            "marginCoin": "USDT",
            "leverage": str(leverage),
        })

    def get_positions(self, symbol: str | None = None) -> list:
        params = {"productType": "USDT-FUTURES", "marginCoin": "USDT"}
        if symbol:
            params["symbol"] = symbol
        data = self._get("/api/v2/mix/position/single-position", params)
        positions = data.get("data", [])
        # Bybit互換形式
        return [{"size": p.get("total", "0"), "side": p.get("holdSide", "")} for p in positions]

    def get_wallet_balance(self) -> dict:
        data = self._get("/api/v2/mix/account/accounts", {"productType": "USDT-FUTURES"})
        accounts = data.get("data", [])
        # Bybit互換形式に変換
        usdt_balance = "0"
        for acc in accounts:
            if acc.get("marginCoin") == "USDT":
                usdt_balance = acc.get("available", "0")
                break
        return {
            "list": [{
                "coin": [{
                    "coin": "USDT",
                    "availableToWithdraw": usdt_balance,
                }]
            }]
        }

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
        bg_side = side.lower()  # "Buy" -> "buy", "Sell" -> "sell"

        data = {
            "symbol": symbol,
            "productType": "USDT-FUTURES",
            "marginMode": "crossed",
            "marginCoin": "USDT",
            "side": bg_side,
            "orderType": order_type.lower(),
            "size": qty,
            "force": "gtc" if order_type.lower() == "limit" else "ioc",
        }
        if price:
            data["price"] = price
        if take_profit:
            data["presetStopSurplusPrice"] = take_profit
        if stop_loss:
            data["presetStopLossPrice"] = stop_loss

        return self._post("/api/v2/mix/order/place-order", data)

    def cancel_all_orders(self, symbol: str) -> dict:
        return self._post("/api/v2/mix/order/cancel-all-orders", {
            "symbol": symbol,
            "productType": "USDT-FUTURES",
            "marginCoin": "USDT",
        })

    def get_instrument_info(self, symbol: str) -> dict:
        """銘柄情報 → Bybit互換形式で返す"""
        resp = self.session.get(
            f"{BASE_URL}/api/v2/mix/market/contracts",
            params={"productType": "USDT-FUTURES", "symbol": symbol},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data", [])
        if not items:
            raise ValueError(f"銘柄情報取得失敗: {symbol}")
        info = items[0]
        # pricePlaceは小数桁数(例: "4") → tick_sizeに変換(例: "0.0001")
        price_place = int(info.get("pricePlace", 4))
        tick_size = 1 / (10 ** price_place) if price_place > 0 else 1
        # Bybit互換形式
        return {
            "lotSizeFilter": {
                "minOrderQty": info.get("minTradeNum", "1"),
                "qtyStep": info.get("sizeMultiplier", "1"),
            },
            "priceFilter": {
                "tickSize": str(tick_size),
            },
        }
