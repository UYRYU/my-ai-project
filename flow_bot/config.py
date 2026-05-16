"""Unusual Options Flow Bot - Configuration"""

import os

# Alpaca API
ALPACA_API_KEY = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_DATA_URL = "https://data.alpaca.markets"

# 監視銘柄
WATCHLIST = [
    # 指数ETF
    "SPY",   # S&P 500
    "QQQ",   # NASDAQ 100
    "IWM",   # Russell 2000
    "DIA",   # Dow Jones
    # コモディティETF
    "USO",   # 原油
    "GLD",   # 金
    "SLV",   # 銀
    # クリプトETF
    "IBIT",  # BTC (BlackRock)
    "BITO",  # BTC (ProShares)
    "ETHA",  # ETH (BlackRock)
]

# 検出条件
MIN_VOLUME_OI_RATIO = 5.0   # Volume/OI比 5倍以上
MIN_PREMIUM_USD = 100_000   # プレミアム $100k以上
MAX_DTE = 30                # 満期まで30日以内
SIDE_FILTER = "call"        # CALLのみ

# スキャン間隔（秒）
SCAN_INTERVAL = 60
