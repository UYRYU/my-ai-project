"""モックデータコレクター。開発・テスト用。"""

import random
from datetime import datetime, timedelta, timezone

from .base import BaseCollector, Trade

MOCK_MARKETS = [
    ("market_001", "Will BTC reach $100k by end of 2026?"),
    ("market_002", "US Presidential Election 2028 - Democrat Win?"),
    ("market_003", "Will ETH flip BTC market cap by 2027?"),
    ("market_004", "Fed Rate Cut in Q2 2026?"),
    ("market_005", "Will AI pass Turing Test by 2027?"),
]


class MockCollector(BaseCollector):
    """ランダムなモック取引データを生成するコレクター。"""

    def __init__(self, cluster_mode: bool = True):
        self._cluster_mode = cluster_mode
        self._call_count = 0

    async def fetch_recent_trades(self, wallet_address: str) -> list[Trade]:
        self._call_count += 1
        trades: list[Trade] = []
        num_trades = random.randint(0, 3)

        for i in range(num_trades):
            market_id, market_title = random.choice(MOCK_MARKETS)

            # クラスタモード: 同一マーケット・同方向の取引を高確率で生成
            if self._cluster_mode and self._call_count % 3 == 0:
                market_id, market_title = MOCK_MARKETS[0]
                outcome = "Yes"
                side = "buy"
            else:
                outcome = random.choice(["Yes", "No"])
                side = random.choice(["buy", "sell"])

            trades.append(
                Trade(
                    tx_hash=f"0xmock_{wallet_address[:8]}_{self._call_count}_{i}",
                    wallet_address=wallet_address,
                    market_id=market_id,
                    market_title=market_title,
                    outcome=outcome,
                    side=side,
                    amount_usdc=round(random.uniform(10, 5000), 2),
                    price=round(random.uniform(0.05, 0.95), 4),
                    timestamp=datetime.now(timezone.utc)
                    - timedelta(seconds=random.randint(0, 300)),
                )
            )
        return trades
