"""MEXC先物API クライアント"""

import hashlib
import hmac
import time
import requests
from urllib.parse import urlencode

BASE_URL = "https://contract.mexc.com"


class MexcFuturesClient:
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def _sign(self, params: dict) -> str:
        timestamp = str(int(time.time() * 1000))
        params["timestamp"] = timestamp
        query = urlencode(sorted(params.items()))
        signature = hmac.new(
            self.api_secret.encode(), query.encode(), hashlib.sha256
        ).hexdigest()
        return signature, timestamp

    def _headers(self, params: dict) -> dict:
        signature, timestamp = self._sign(params)
        return {
            "ApiKey": self.api_key,
            "Request-Time": timestamp,
            "Signature": signature,
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: dict | None = None):
        params = params or {}
        headers = self._headers(params)
        url = f"{BASE_URL}{path}"
        if params:
            url += "?" + urlencode(params)
        resp = self.session.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, data: dict | None = None):
        data = data or {}
        headers = self._headers(data)
        resp = self.session.post(
            f"{BASE_URL}{path}", json=data, headers=headers, timeout=10
        )
        resp.raise_for_status()
        return resp.json()

    # === 公開API ===

    def get_ticker(self, symbol: str) -> dict:
        """現在価格を取得"""
        resp = self.session.get(
            f"{BASE_URL}/api/v1/contract/ticker?symbol={symbol}", timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("success") and data.get("data"):
            return data["data"]
        raise ValueError(f"ティッカー取得失敗: {data}")

    def get_klines(self, symbol: str, interval: str, limit: int = 100) -> list:
        """ローソク足データを取得"""
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        resp = self.session.get(
            f"{BASE_URL}/api/v1/contract/kline/{symbol}",
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("success") and data.get("data"):
            return data["data"]
        raise ValueError(f"K線取得失敗: {data}")

    # === 認証API ===

    def set_leverage(self, symbol: str, leverage: int, side: int = 0):
        """レバレッジ設定 (side: 0=両方, 1=ロング, 2=ショート)"""
        data = {"symbol": symbol, "leverage": leverage, "openType": side}
        return self._post("/api/v1/private/position/change_leverage", data)

    def get_positions(self, symbol: str | None = None) -> list:
        """ポジション取得"""
        params = {}
        if symbol:
            params["symbol"] = symbol
        return self._get("/api/v1/private/position/open_positions", params)

    def place_order(
        self,
        symbol: str,
        side: int,
        vol: float,
        order_type: int = 5,
        price: float | None = None,
        open_type: int = 1,
        stop_loss_price: float | None = None,
        take_profit_price: float | None = None,
    ) -> dict:
        """
        注文発注
        side: 1=買い(ロング), 2=売り(ロング決済), 3=売り(ショート), 4=買い(ショート決済)
        order_type: 1=指値, 2=Post Only, 3=IOC, 4=FOK, 5=成行
        open_type: 1=isolated, 2=cross
        """
        data = {
            "symbol": symbol,
            "side": side,
            "vol": vol,
            "type": order_type,
            "openType": open_type,
        }
        if price is not None:
            data["price"] = price
        if stop_loss_price is not None:
            data["stopLossPrice"] = stop_loss_price
        if take_profit_price is not None:
            data["takeProfitPrice"] = take_profit_price
        return self._post("/api/v1/private/order/submit", data)

    def cancel_all_orders(self, symbol: str) -> dict:
        """全注文キャンセル"""
        data = {"symbol": symbol}
        return self._post("/api/v1/private/order/cancel_all", data)

    def get_open_orders(self, symbol: str) -> dict:
        """未約定注文取得"""
        params = {"symbol": symbol}
        return self._get("/api/v1/private/order/list/open_orders/" + symbol, params)
