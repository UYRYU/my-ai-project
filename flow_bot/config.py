"""Unusual Options Flow Bot - Configuration"""

import os

# Polygon.io API
POLYGON_API_KEY = os.environ.get("POLYGON_API_KEY", "")
POLYGON_BASE_URL = "https://api.polygon.io"

# 監視銘柄
WATCHLIST = [
    "SPY", "QQQ", "AAPL", "NVDA", "TSLA",
    "MSFT", "META", "AMZN", "AMD", "COIN",
]

# 検出条件
MIN_VOLUME_OI_RATIO = 5.0   # Volume/OI比 5倍以上
MIN_PREMIUM_USD = 100_000   # プレミアム $100k以上
MAX_DTE = 30                # 満期まで30日以内
SIDE_FILTER = "call"        # CALLのみ

# スキャン間隔（秒）
SCAN_INTERVAL = 60

# 1銘柄あたりの詳細取得数上限（APIコール節約）
MAX_CONTRACTS_PER_TICKER = 20
