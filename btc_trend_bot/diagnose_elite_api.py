"""Diagnose which Bitget endpoints work with the Elite Trader API key.

Run:
    python -m btc_trend_bot.diagnose_elite_api
"""

import os
import sys

from loguru import logger

from btc_trend_bot.env_loader import load_env
from btc_trend_bot.exchange.bitget_futures import BitgetFuturesClient
from btc_trend_bot.exchange.models import ExchangeConfig


def main() -> int:
    load_env()
    logger.remove()
    logger.add(sys.stderr, level="INFO",
               format="<green>{time:HH:mm:ss}</green> | <level>{level:7s}</level> | {message}")

    cfg = ExchangeConfig(
        exchange_name="bitget",
        api_key=os.environ.get("BITGET_API_KEY", ""),
        api_secret=os.environ.get("BITGET_API_SECRET", ""),
        passphrase=os.environ.get("BITGET_PASSPHRASE", ""),
        testnet=False,
        base_url="https://api.bitget.com",
        product_type="USDT-FUTURES",
        margin_mode="crossed",
    )
    client = BitgetFuturesClient(cfg, live_confirmed=True)

    print("\n========== 1) /api/v2/mix/account/accounts ==========")
    try:
        result = client._request(
            "GET", "/api/v2/mix/account/accounts",
            params={"productType": "USDT-FUTURES"},
        )
        print(result)
    except Exception as exc:
        print(f"FAIL: {exc}")

    print("\n========== 2) /api/v2/mix/account/account (single) ==========")
    try:
        result = client._request(
            "GET", "/api/v2/mix/account/account",
            params={"symbol": "BTCUSDT", "productType": "USDT-FUTURES",
                    "marginCoin": "USDT"},
        )
        print(result)
    except Exception as exc:
        print(f"FAIL: {exc}")

    print("\n========== 3) /api/v2/mix/position/all-position ==========")
    try:
        result = client._request(
            "GET", "/api/v2/mix/position/all-position",
            params={"productType": "USDT-FUTURES", "marginCoin": "USDT"},
        )
        print(result)
    except Exception as exc:
        print(f"FAIL: {exc}")

    print("\n========== 4) /api/v2/copy/mix-trader/order-current-track ==========")
    try:
        result = client._request(
            "GET", "/api/v2/copy/mix-trader/order-current-track",
            params={"productType": "USDT-FUTURES"},
        )
        print(result)
    except Exception as exc:
        print(f"FAIL: {exc}")

    print("\n========== 5) /api/v2/copy/mix-trader/config-query-symbols ==========")
    try:
        result = client._request(
            "GET", "/api/v2/copy/mix-trader/config-query-symbols",
            params={"productType": "USDT-FUTURES"},
        )
        print(result)
    except Exception as exc:
        print(f"FAIL: {exc}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
