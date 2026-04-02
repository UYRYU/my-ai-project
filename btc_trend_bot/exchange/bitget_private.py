"""Bitget private (authenticated) API adapter."""

import base64
import hashlib
import hmac
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import requests
from loguru import logger

from btc_trend_bot.exchange.base import BasePrivateExchange
from btc_trend_bot.exchange.bitget_public import BitgetPublicClient
from btc_trend_bot.exchange.models import (
    ExchangeConfig,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderType,
    Ticker,
)

RATE_LIMIT_DELAY = 0.1  # seconds between requests
MAX_RETRIES = 3


class BitgetPrivateClient(BasePrivateExchange):
    """Bitget v2 authenticated REST API client.

    Extends public market data with order management and account queries.
    All order-related methods enforce a testnet safety check: if
    ``config.testnet`` is ``False`` the caller must explicitly pass
    ``live_confirmed=True`` when constructing the client.
    """

    def __init__(
        self,
        config: ExchangeConfig,
        live_confirmed: bool = False,
    ) -> None:
        if not config.api_key or not config.api_secret or not config.passphrase:
            raise ValueError(
                "BitgetPrivateClient requires api_key, api_secret, and passphrase "
                "to be set in ExchangeConfig"
            )

        if not config.testnet and not live_confirmed:
            raise RuntimeError(
                "Live trading is disabled by default. Set live_confirmed=True "
                "when constructing BitgetPrivateClient to acknowledge live mode."
            )

        super().__init__(config)
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})
        self._last_request_ts: float = 0.0

        # Delegate public endpoints to BitgetPublicClient
        self._public = BitgetPublicClient(config)

        logger.info(
            "BitgetPrivateClient initialised | testnet={} base_url={}",
            self.config.testnet,
            self.config.base_url,
        )

    # ------------------------------------------------------------------
    # Signing
    # ------------------------------------------------------------------

    def _sign(self, timestamp: str, method: str, path: str, body: str = "") -> str:
        """Create HMAC-SHA256 signature for Bitget API authentication.

        The message is composed as: ``timestamp + METHOD + path + body``
        and signed with the API secret. The result is base64-encoded.
        """
        message = timestamp + method.upper() + path + body
        mac = hmac.new(
            self.config.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        )
        return base64.b64encode(mac.digest()).decode("utf-8")

    def _auth_headers(self, method: str, path: str, body: str = "") -> dict[str, str]:
        """Build the full set of authentication headers."""
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
    # Internal request helpers
    # ------------------------------------------------------------------

    def _private_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        body: Optional[dict] = None,
    ) -> dict:
        """Execute an authenticated request with retry and rate limiting."""
        import json as _json

        url = self.config.base_url.rstrip("/") + endpoint
        body_str = _json.dumps(body) if body else ""

        # For GET requests, build the query string into the path for signing
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
                    response = self._session.get(
                        url, params=params, headers=headers, timeout=30
                    )
                else:
                    response = self._session.post(
                        url, data=body_str, headers=headers, timeout=30
                    )

                response.raise_for_status()
                result: dict = response.json()

                code = result.get("code", "")
                if code != "00000":
                    msg = result.get("msg", "unknown error")
                    logger.error(
                        "Bitget API error | code={} msg={} endpoint={}",
                        code,
                        msg,
                        endpoint,
                    )
                    raise RuntimeError(f"Bitget API error code={code}: {msg}")

                return result

            except (requests.RequestException, RuntimeError) as exc:
                backoff = 2 ** (attempt - 1)
                if attempt < MAX_RETRIES:
                    logger.warning(
                        "Request failed (attempt {}/{}), retrying in {}s: {}",
                        attempt,
                        MAX_RETRIES,
                        backoff,
                        exc,
                    )
                    time.sleep(backoff)
                else:
                    logger.error(
                        "Request failed after {} attempts: {}", MAX_RETRIES, exc
                    )
                    raise

        raise RuntimeError("Unreachable: all retries exhausted")

    # ------------------------------------------------------------------
    # Public endpoint delegation
    # ------------------------------------------------------------------

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: Optional[str] = None,
        limit: int = 1000,
    ) -> pd.DataFrame:
        """Delegate to the public client."""
        return self._public.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)

    def fetch_ticker(self, symbol: str) -> Ticker:
        """Delegate to the public client."""
        return self._public.fetch_ticker(symbol)

    def get_server_time(self) -> pd.Timestamp:
        """Delegate to the public client."""
        return self._public.get_server_time()

    # ------------------------------------------------------------------
    # Order management
    # ------------------------------------------------------------------

    def place_order(self, order: OrderRequest) -> OrderResult:
        """Place a new spot order.

        Endpoint: POST /api/v2/spot/trade/place-order
        """
        if order.size < self.config.min_order_size_btc:
            raise ValueError(
                f"Order size {order.size} is below minimum "
                f"{self.config.min_order_size_btc}"
            )

        client_oid = order.client_order_id or uuid.uuid4().hex[:32]

        body: dict = {
            "symbol": order.symbol,
            "side": order.side.value,
            "orderType": order.order_type.value,
            "size": str(order.size),
            "clientOid": client_oid,
            "force": "gtc",
        }

        if order.order_type == OrderType.LIMIT:
            if order.price is None:
                raise ValueError("Limit orders require a price")
            body["price"] = str(order.price)

        logger.info(
            "Placing {} {} order | symbol={} size={} price={}",
            order.side.value,
            order.order_type.value,
            order.symbol,
            order.size,
            order.price,
        )

        result = self._private_request(
            "POST", "/api/v2/spot/trade/place-order", body=body
        )

        data = result.get("data", {})
        order_id = str(data.get("orderId", ""))

        return OrderResult(
            order_id=order_id,
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

    def cancel_order(self, order_id: str, symbol: str) -> bool:
        """Cancel an existing order.

        Endpoint: POST /api/v2/spot/trade/cancel-order
        """
        logger.info("Cancelling order {} for {}", order_id, symbol)

        body = {
            "symbol": symbol,
            "orderId": order_id,
        }

        try:
            self._private_request(
                "POST", "/api/v2/spot/trade/cancel-order", body=body
            )
            logger.info("Order {} cancelled successfully", order_id)
            return True
        except RuntimeError as exc:
            logger.error("Failed to cancel order {}: {}", order_id, exc)
            return False

    # ------------------------------------------------------------------
    # Account queries
    # ------------------------------------------------------------------

    def get_balance(self, currency: str = "USDT") -> float:
        """Get available balance for a currency.

        Endpoint: GET /api/v2/spot/account/assets
        """
        result = self._private_request(
            "GET", "/api/v2/spot/account/assets", params={"coin": currency}
        )
        assets = result.get("data", [])

        for asset in assets:
            if asset.get("coin", "").upper() == currency.upper():
                available = float(asset.get("available", 0.0))
                logger.debug("Balance for {}: {}", currency, available)
                return available

        logger.warning("No balance found for {}", currency)
        return 0.0

    def get_open_orders(self, symbol: str) -> list[OrderResult]:
        """Get all unfilled orders for a symbol.

        Endpoint: GET /api/v2/spot/trade/unfilled-orders
        """
        result = self._private_request(
            "GET",
            "/api/v2/spot/trade/unfilled-orders",
            params={"symbol": symbol},
        )

        orders_data = result.get("data", [])
        orders: list[OrderResult] = []

        for o in orders_data:
            side_str = o.get("side", "buy").lower()
            order_type_str = o.get("orderType", "market").lower()

            orders.append(
                OrderResult(
                    order_id=str(o.get("orderId", "")),
                    client_order_id=str(o.get("clientOid", "")),
                    symbol=str(o.get("symbol", symbol)),
                    side=OrderSide(side_str),
                    order_type=OrderType(order_type_str),
                    size=float(o.get("size", 0)),
                    price=float(o.get("price", 0)),
                    filled_size=float(o.get("baseVolume", 0)),
                    status=str(o.get("status", "open")),
                    fee=float(o.get("fee", 0)),
                    timestamp=pd.Timestamp(
                        int(o.get("cTime", 0)), unit="ms", tz="UTC"
                    ),
                    metadata=o,
                )
            )

        logger.debug("Found {} open orders for {}", len(orders), symbol)
        return orders

    def get_position(self, symbol: str) -> Optional[dict]:
        """Get current position information for a symbol.

        For spot trading, this returns balance information for the base
        currency of the pair. Returns ``None`` if no holdings are found.
        """
        # Extract base currency from the symbol (e.g. "BTC" from "BTCUSDT")
        base_currency = symbol.replace("USDT", "").replace("USDC", "")

        result = self._private_request(
            "GET",
            "/api/v2/spot/account/assets",
            params={"coin": base_currency},
        )

        assets = result.get("data", [])
        for asset in assets:
            if asset.get("coin", "").upper() == base_currency.upper():
                available = float(asset.get("available", 0.0))
                frozen = float(asset.get("frozen", 0.0))
                total = available + frozen

                if total <= 0:
                    logger.debug("No position in {} for {}", base_currency, symbol)
                    return None

                position = {
                    "symbol": symbol,
                    "base_currency": base_currency,
                    "total": total,
                    "available": available,
                    "frozen": frozen,
                }
                logger.debug("Position for {}: {}", symbol, position)
                return position

        logger.debug("No asset entry found for {}", base_currency)
        return None
