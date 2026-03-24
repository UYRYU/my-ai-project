"""Notification system: terminal output and optional Discord webhook."""

from __future__ import annotations

import json
import logging
from typing import Optional

import httpx

from .config import Config
from .models import SignalResult

logger = logging.getLogger("polymarket_bot")


class Notifier:
    """Send notifications for detected signals."""

    def __init__(self, config: Config) -> None:
        self.config = config

    async def notify(self, signal: SignalResult) -> None:
        """Send notification via all configured channels."""
        self._print_terminal(signal)

        if self.config.enable_discord and self.config.discord_webhook_url:
            await self._send_discord(signal)

    def _print_terminal(self, signal: SignalResult) -> None:
        """Print signal to terminal in a readable format."""
        d = signal.to_dict()
        print("\n" + "-" * 50)
        print("  SIGNAL DETECTED")
        print("-" * 50)
        print(f"  Time:          {d['timestamp']}")
        print(f"  Market:        {d['market_question'][:60]}")
        print(f"  Condition ID:  {d['condition_id'][:16]}...")
        print(f"  YES bid/ask:   {d['yes_best_bid']} / {d['yes_best_ask']}")
        print(f"  NO  bid/ask:   {d['no_best_bid']} / {d['no_best_ask']}")
        print(f"  Mispricing:    {d['mispricing_score']}")
        print(f"  Spread:        {d['spread_score']}")
        print(f"  Liquidity:     {d['liquidity_score']}")
        print(f"  Momentum:      {d['momentum_score']} ({d['momentum_label']})")
        print(f"  Confidence:    {d['confidence_score']}")
        print(f"  Action:        {d['recommended_action']}")
        print(f"  Expected Edge: {d['expected_edge']}")
        print(f"  Reason:        {d['reason']}")
        print("-" * 50)

    async def _send_discord(self, signal: SignalResult) -> None:
        """Send signal notification to Discord webhook."""
        d = signal.to_dict()
        embed = {
            "title": "Polymarket Signal Detected",
            "color": 0x00FF00 if d["confidence_score"] >= 80 else 0xFFFF00,
            "fields": [
                {"name": "Market", "value": d["market_question"][:100], "inline": False},
                {"name": "Confidence", "value": str(d["confidence_score"]), "inline": True},
                {"name": "Mispricing", "value": str(d["mispricing_score"]), "inline": True},
                {"name": "Action", "value": str(d["recommended_action"]), "inline": True},
                {"name": "Edge", "value": str(d["expected_edge"]), "inline": True},
                {"name": "Reason", "value": d["reason"][:200], "inline": False},
            ],
            "timestamp": d["timestamp"],
        }

        payload = {"embeds": [embed]}

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    self.config.discord_webhook_url,
                    json=payload,
                )
                resp.raise_for_status()
                logger.debug("Discord notification sent")
        except Exception as e:
            logger.warning("Failed to send Discord notification: %s", e)
