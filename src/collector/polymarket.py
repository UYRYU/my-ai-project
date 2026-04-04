"""Polymarket APIコレクター。実APIへの接続用。

NOTE: Polymarket APIの仕様は変更される可能性があるため、
      このコレクターは差し替え可能な設計にしています。
      現時点ではCLOB APIのエンドポイントを使用しています。
"""

import logging
from datetime import datetime, timezone

import httpx

from .base import BaseCollector, Trade

logger = logging.getLogger(__name__)

CLOB_API_BASE = "https://clob.polymarket.com"
GAMMA_API_BASE = "https://gamma-api.polymarket.com"


class PolymarketCollector(BaseCollector):
    """Polymarket CLOB APIからデータを取得するコレクター。"""

    def __init__(self, timeout: float = 15.0):
        self._client = httpx.AsyncClient(timeout=timeout)

    async def fetch_recent_trades(self, wallet_address: str) -> list[Trade]:
        trades: list[Trade] = []
        try:
            # CLOB APIで取引履歴を取得
            resp = await self._client.get(
                f"{GAMMA_API_BASE}/trades",
                params={"maker_address": wallet_address, "limit": 50},
            )
            resp.raise_for_status()
            data = resp.json()

            for item in data if isinstance(data, list) else data.get("data", []):
                try:
                    trades.append(self._parse_trade(item, wallet_address))
                except (KeyError, ValueError) as e:
                    logger.warning("取引データのパースに失敗: %s - %s", e, item)
                    continue

        except httpx.HTTPStatusError as e:
            logger.error("API HTTPエラー (%s): %s", wallet_address[:10], e)
        except httpx.RequestError as e:
            logger.error("APIリクエストエラー (%s): %s", wallet_address[:10], e)
        except Exception as e:
            logger.error("予期しないエラー (%s): %s", wallet_address[:10], e)

        return trades

    def _parse_trade(self, item: dict, wallet_address: str) -> Trade:
        """APIレスポンスをTradeオブジェクトに変換する。"""
        timestamp_raw = item.get("timestamp") or item.get("created_at", "")
        if isinstance(timestamp_raw, (int, float)):
            ts = datetime.fromtimestamp(timestamp_raw, tz=timezone.utc)
        else:
            ts = datetime.fromisoformat(str(timestamp_raw).replace("Z", "+00:00"))

        return Trade(
            tx_hash=str(item.get("id", item.get("tx_hash", "unknown"))),
            wallet_address=wallet_address,
            market_id=str(item.get("market", item.get("condition_id", "unknown"))),
            market_title=str(item.get("market_slug", item.get("question", "N/A"))),
            outcome=str(item.get("outcome", item.get("asset_id", "Unknown"))),
            side=str(item.get("side", "buy")).lower(),
            amount_usdc=float(item.get("size", item.get("amount", 0))),
            price=float(item.get("price", 0)),
            timestamp=ts,
        )

    async def close(self) -> None:
        await self._client.aclose()
