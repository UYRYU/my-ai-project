"""Discord Webhook通知モジュール。"""

import logging

import httpx

from src.processor.signal_detector import Signal

logger = logging.getLogger(__name__)


class DiscordNotifier:
    def __init__(self, webhook_url: str = ""):
        self._webhook_url = webhook_url
        self._client = httpx.AsyncClient(timeout=10.0)

    @property
    def is_enabled(self) -> bool:
        return bool(self._webhook_url)

    async def send_signal(self, signal: Signal) -> bool:
        if not self.is_enabled:
            return False

        strength_emoji = "🔴" if signal.is_strong else "🟡"
        wallets_str = "\n".join(
            f"  `{w[:10]}...{w[-6:]}`" for w in signal.wallets
        )

        embed = {
            "title": f"{strength_emoji} Polymarket Signal [{signal.strength_label}]",
            "color": 0xFF0000 if signal.is_strong else 0xFFAA00,
            "fields": [
                {
                    "name": "Market",
                    "value": signal.market_title,
                    "inline": False,
                },
                {
                    "name": "Direction",
                    "value": signal.direction,
                    "inline": True,
                },
                {
                    "name": "Wallets",
                    "value": str(signal.wallet_count),
                    "inline": True,
                },
                {
                    "name": "Total Amount",
                    "value": f"${signal.total_amount_usdc:,.2f}",
                    "inline": True,
                },
                {
                    "name": "Avg Price",
                    "value": f"{signal.avg_price:.2%}",
                    "inline": True,
                },
                {
                    "name": "Time Window",
                    "value": (
                        f"{signal.first_trade_time.strftime('%H:%M:%S')} - "
                        f"{signal.last_trade_time.strftime('%H:%M:%S')}"
                    ),
                    "inline": True,
                },
                {
                    "name": "Tracked Wallets",
                    "value": wallets_str,
                    "inline": False,
                },
            ],
        }

        payload = {"embeds": [embed]}

        try:
            resp = await self._client.post(self._webhook_url, json=payload)
            resp.raise_for_status()
            logger.info("Discord通知送信成功: %s", signal.market_id)
            return True
        except httpx.HTTPStatusError as e:
            logger.error("Discord通知HTTPエラー: %s", e)
        except httpx.RequestError as e:
            logger.error("Discord通知リクエストエラー: %s", e)
        except Exception as e:
            logger.error("Discord通知予期しないエラー: %s", e)
        return False

    async def close(self) -> None:
        await self._client.aclose()
