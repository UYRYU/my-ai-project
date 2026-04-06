"""Bitget USDT-M Futures API client for copy trading.

Provides authenticated access to Bitget's v2 mix (futures) endpoints:
- Place/cancel futures orders
- Get futures positions and balance
- Set leverage and margin mode
- Fetch futures OHLCV data

All endpoints use /api/v2/mix/ prefix.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json as _json
import time
import uuid
from typing import Optional

import pandas as pd
import requests
from loguru import logger

from btc_trend_bot.exchange.models import (
    ExchangeConfig,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderType,
    Ticker,
)

RATE_LIMIT_DELAY = 0.1
MAX_RETRIES = 3

# Bitget futures symbol format
FUTURES_SYMBOL = "BTCUSDT"
PRODUCT_TYPE = "USDT-FUTURES"

# Granularity mapping for futures candles
GRANULARITY_MAP: dict[str, str] = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1H", "4h": "4H", "1d": "1D", "1w": "1W",
}


class BitgetFuturesClient:
    """Bitget v2 USDT-M Futures client for copy trading."""

    def __init__(self, config: ExchangeConfig, live_confirmed: bool = False) -> None:
        if not config.api_key or not config.api_secret or not config.passphrase:
            raise ValueError("api_key, api_secret, and passphrase are required")

        if not config.testnet and not live_confirmed:
            raise RuntimeError(
                "Live trading disabled by default. Set live_confirmed=True to acknowledge."
            )

        self.config = config
        self.product_type = config.product_type or PRODUCT_TYPE
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})
        self._last_request_ts: float = 0.0

        logger.info(
            "BitgetFuturesClient init | product={} testnet={} base_url={}",
            self.product_type, config.testnet, config.base_url,
        )

    # ------------------------------------------------------------------
    # Signing
    # ------------------------------------------------------------------

    def _sign(self, timestamp: str, method: str, path: str, body: str = "") -> str:
        message = timestamp + method.upper() + path + body
        mac = hmac.new(
            self.config.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        )
        return base64.b64encode(mac.digest()).decode("utf-8")

    def _auth_headers(self, method: str, path: str, body: str = "") -> dict:
        timestamp = str(int(time.time() * 1000))
        signature = self._sign(timestamp, method, path, body)
        return {
            "ACCESS-KEY": self.config.api_key,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": self.config.passphrase,
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Request helpers
    # ------------------------------------------------------------------

    def _request(self, method: str, endpoint: str,
                 params: Optional[dict] = None, body: Optional[dict] = None) -> dict:
        url = self.config.base_url.rstrip("/") + endpoint
        body_str = _json.dumps(body) if body else ""

        if method.upper() == "GET" and params:
            query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
            sign_path = endpoint + "?" + query
        else:
            sign_path = endpoint

        for attempt in range(1, MAX_RETRIES + 1):
            elapsed = time.monotonic() - self._last_request_ts
            if elapsed < RATE_LIMIT_DELAY:
                time.sleep(RATE_LIMIT_DELAY - elapsed)

            headers = self._auth_headers(method.upper(), sign_path, body_str)

            try:
                self._last_request_ts = time.monotonic()
                if method.upper() == "GET":
                    resp = self._session.get(url, params=params, headers=headers, timeout=30)
                else:
                    resp = self._session.post(url, data=body_str, headers=headers, timeout=30)

                resp.raise_for_status()
                result = resp.json()

                code = result.get("code", "")
                if code != "00000":
                    msg = result.get("msg", "unknown")
                    logger.error("Bitget API error | code={} msg={}", code, msg)
                    raise RuntimeError(f"Bitget API error code={code}: {msg}")

                return result

            except (requests.RequestException, RuntimeError) as exc:
                backoff = 2 ** (attempt - 1)
                if attempt < MAX_RETRIES:
                    logger.warning("Request failed ({}/{}), retry in {}s: {}",
                                   attempt, MAX_RETRIES, backoff, exc)
                    time.sleep(backoff)
                else:
                    raise

        raise RuntimeError("All retries exhausted")

    # ------------------------------------------------------------------
    # Account setup
    # ------------------------------------------------------------------

    def set_leverage(self, symbol: str, leverage: int, side: str = "long") -> dict:
        """Set leverage for a symbol.

        Endpoint: POST /api/v2/mix/account/set-leverage
        """
        body = {
            "symbol": symbol,
            "productType": self.product_type,
            "marginCoin": "USDT",
            "leverage": str(leverage),
            "holdSide": side,
        }
        result = self._request("POST", "/api/v2/mix/account/set-leverage", body=body)
        logger.info("Leverage set: {} {}x ({})", symbol, leverage, side)
        return result.get("data", {})

    def set_margin_mode(self, symbol: str, margin_mode: str = "crossed") -> dict:
        """Set margin mode (crossed/isolated).

        Endpoint: POST /api/v2/mix/account/set-margin-mode
        """
        body = {
            "symbol": symbol,
            "productType": self.product_type,
            "marginCoin": "USDT",
            "marginMode": margin_mode,
        }
        result = self._request("POST", "/api/v2/mix/account/set-margin-mode", body=body)
        logger.info("Margin mode set: {} {}", symbol, margin_mode)
        return result.get("data", {})

    # ------------------------------------------------------------------
    # Order management
    # ------------------------------------------------------------------

    def place_order(self, order: OrderRequest) -> OrderResult:
        """Place a futures order.

        Endpoint: POST /api/v2/mix/order/place-order
        """
        client_oid = order.client_order_id or uuid.uuid4().hex[:32]

        # Futures: side is "buy" for open long, "sell" for close long
        # tradeSide: "open" or "close"
        body: dict = {
            "symbol": order.symbol,
            "productType": self.product_type,
            "marginMode": self.config.margin_mode,
            "marginCoin": "USDT",
            "size": str(order.size),
            "side": order.side.value,
            "tradeSide": "open" if not order.reduce_only else "close",
            "orderType": order.order_type.value,
            "clientOid": client_oid,
            "force": "gtc",
        }

        if order.order_type == OrderType.LIMIT and order.price is not None:
            body["price"] = str(order.price)

        # Attach SL/TP as preset
        if order.stop_loss is not None:
            body["presetStopLossPrice"] = str(order.stop_loss)
        if order.take_profit is not None:
            body["presetStopSurplusPrice"] = str(order.take_profit)

        logger.info(
            "Placing futures {} {} | {} size={} price={}",
            order.side.value, order.order_type.value,
            order.symbol, order.size, order.price,
        )

        result = self._request("POST", "/api/v2/mix/order/place-order", body=body)
        data = result.get("data", {})

        return OrderResult(
            order_id=str(data.get("orderId", "")),
            client_order_id=client_oid,
            symbol=order.symbol,
            side=order.side,
            order_type=order.order_type,
            size=order.size,
            price=order.price or 0.0,
            filled_size=0.0,
            status="submitted",
            fee=0.0,
            timestamp=pd.Timestamp.now(tz="UTC"),
            metadata=data,
        )

    def close_position(self, symbol: str, side: str = "long") -> OrderResult:
        """Close an entire position with a market order.

        This is a convenience method that uses the flash-close endpoint.
        Endpoint: POST /api/v2/mix/order/close-positions
        """
        body = {
            "symbol": symbol,
            "productType": self.product_type,
            "holdSide": side,
        }
        logger.info("Closing {} position for {}", side, symbol)
        result = self._request("POST", "/api/v2/mix/order/close-positions", body=body)
        data = result.get("data", {})

        return OrderResult(
            order_id=str(data.get("orderId", "")),
            client_order_id="",
            symbol=symbol,
            side=OrderSide.SELL if side == "long" else OrderSide.BUY,
            order_type=OrderType.MARKET,
            size=0.0,
            price=0.0,
            filled_size=0.0,
            status="submitted",
            fee=0.0,
            timestamp=pd.Timestamp.now(tz="UTC"),
            metadata=data,
        )

    def cancel_order(self, order_id: str, symbol: str) -> bool:
        """Cancel a futures order.

        Endpoint: POST /api/v2/mix/order/cancel-order
        """
        body = {
            "symbol": symbol,
            "productType": self.product_type,
            "orderId": order_id,
        }
        try:
            self._request("POST", "/api/v2/mix/order/cancel-order", body=body)
            logger.info("Order {} cancelled", order_id)
            return True
        except RuntimeError as exc:
            logger.error("Failed to cancel {}: {}", order_id, exc)
            return False

    # ------------------------------------------------------------------
    # Account queries
    # ------------------------------------------------------------------

    def get_balance(self, currency: str = "USDT") -> float:
        """Get futures account balance.

        Endpoint: GET /api/v2/mix/account/accounts
        """
        result = self._request(
            "GET", "/api/v2/mix/account/accounts",
            params={"productType": self.product_type},
        )
        for acc in result.get("data", []):
            if acc.get("marginCoin", "").upper() == currency.upper():
                available = float(acc.get("available", 0))
                logger.debug("Futures balance {}: {}", currency, available)
                return available
        return 0.0

    def get_position(self, symbol: str) -> Optional[dict]:
        """Get current futures position.

        Endpoint: GET /api/v2/mix/position/single-position
        """
        result = self._request(
            "GET", "/api/v2/mix/position/single-position",
            params={"symbol": symbol, "productType": self.product_type, "marginCoin": "USDT"},
        )
        positions = result.get("data", [])
        for pos in positions:
            total = float(pos.get("total", 0))
            if total > 0:
                return {
                    "symbol": symbol,
                    "side": pos.get("holdSide", "long"),
                    "size": total,
                    "available": float(pos.get("available", 0)),
                    "entry_price": float(pos.get("openPriceAvg", 0)),
                    "unrealized_pnl": float(pos.get("unrealizedPL", 0)),
                    "leverage": int(pos.get("leverage", 1)),
                    "margin_mode": pos.get("marginMode", "crossed"),
                    "liquidation_price": float(pos.get("liquidationPrice", 0)),
                }
        return None

    def get_open_orders(self, symbol: str) -> list[dict]:
        """Get pending futures orders.

        Endpoint: GET /api/v2/mix/order/orders-pending
        """
        result = self._request(
            "GET", "/api/v2/mix/order/orders-pending",
            params={"symbol": symbol, "productType": self.product_type},
        )
        return result.get("data", {}).get("entrustedList", [])

    # ------------------------------------------------------------------
    # Market data (futures candles)
    # ------------------------------------------------------------------

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 500) -> pd.DataFrame:
        """Fetch futures OHLCV data.

        Endpoint: GET /api/v2/mix/market/candles
        """
        granularity = GRANULARITY_MAP.get(timeframe)
        if not granularity:
            raise ValueError(f"Unsupported timeframe: {timeframe}")

        params = {
            "symbol": symbol,
            "productType": self.product_type,
            "granularity": granularity,
            "limit": str(min(limit, 1000)),
        }

        # Futures candles don't require auth
        url = self.config.base_url.rstrip("/") + "/api/v2/mix/market/candles"
        elapsed = time.monotonic() - self._last_request_ts
        if elapsed < RATE_LIMIT_DELAY:
            time.sleep(RATE_LIMIT_DELAY - elapsed)

        self._last_request_ts = time.monotonic()
        resp = self._session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        body = resp.json()

        if body.get("code") != "00000":
            raise RuntimeError(f"Bitget API error: {body.get('msg')}")

        candles = body.get("data", [])
        if not candles:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        records = []
        for c in candles:
            records.append({
                "timestamp": pd.Timestamp(int(c[0]), unit="ms", tz="UTC"),
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "volume": float(c[5]),
            })

        df = pd.DataFrame.from_records(records)
        df.set_index("timestamp", inplace=True)
        df.sort_index(inplace=True)
        return df

    def fetch_ticker(self, symbol: str) -> Ticker:
        """Fetch futures ticker.

        Endpoint: GET /api/v2/mix/market/ticker
        """
        url = self.config.base_url.rstrip("/") + "/api/v2/mix/market/ticker"
        params = {"symbol": symbol, "productType": self.product_type}

        elapsed = time.monotonic() - self._last_request_ts
        if elapsed < RATE_LIMIT_DELAY:
            time.sleep(RATE_LIMIT_DELAY - elapsed)

        self._last_request_ts = time.monotonic()
        resp = self._session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        body = resp.json()

        if body.get("code") != "00000":
            raise RuntimeError(f"Bitget API error: {body.get('msg')}")

        data = body.get("data", [])
        if not data:
            raise ValueError(f"No ticker for {symbol}")

        t = data[0] if isinstance(data, list) else data
        return Ticker(
            symbol=symbol,
            last_price=float(t.get("lastPr", t.get("last", 0))),
            bid=float(t.get("bidPr", t.get("bestBid", 0))),
            ask=float(t.get("askPr", t.get("bestAsk", 0))),
            volume_24h=float(t.get("baseVolume", 0)),
            timestamp=pd.Timestamp.now(tz="UTC"),
        )
