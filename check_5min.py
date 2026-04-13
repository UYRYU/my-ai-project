#!/usr/bin/env python3
"""5分マーケットがGamma APIから取れるか確認."""

import asyncio
from polymarket_arbitrage.api.gamma_client import GammaClient


async def main():
    async with GammaClient() as client:
        # Try direct markets endpoint
        print("=== Markets endpoint (last 500) ===")
        markets = await client.fetch_markets(limit=500, active=True)
        print(f"Total markets: {len(markets)}")

        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)

        for max_min in [10, 30, 60, 240, 1440]:
            cutoff = now + timedelta(minutes=max_min)
            short = []
            for m in markets:
                if m.end_date is None:
                    continue
                end = m.end_date if m.end_date.tzinfo else m.end_date.replace(tzinfo=timezone.utc)
                if now < end <= cutoff:
                    short.append(m)
            print(f"  Resolving within {max_min} min: {len(short)}")
            for m in short[:3]:
                print(f"    {m.question[:70]}")
                print(f"      Vol=${m.volume:,.0f}, end={m.end_date}")

        # Search keywords in market names
        print(f"\n=== Keyword search in markets ===")
        for kw in ["BTC", "Bitcoin", "Ethereum", "ETH", "5"]:
            matches = [m for m in markets if kw.lower() in m.question.lower()]
            print(f"  '{kw}': {len(matches)} matches")
            for m in matches[:3]:
                print(f"    {m.question[:70]}")

        events = await client.fetch_all_events(active=True, max_events=500)
        print(f"\n=== Events endpoint: {len(events)} ===")

        # Find short-term markets
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)

        for max_min in [10, 30, 60, 240, 1440]:
            cutoff = now + timedelta(minutes=max_min)
            short = []
            for e in events:
                for m in e.markets:
                    if m.end_date is None:
                        continue
                    end = m.end_date if m.end_date.tzinfo else m.end_date.replace(tzinfo=timezone.utc)
                    if now < end <= cutoff:
                        short.append((e, m))
            print(f"\nMarkets resolving within {max_min} min: {len(short)}")
            for e, m in short[:5]:
                print(f"  {m.question[:70]}")
                print(f"    Vol=${m.volume:,.0f}, YES={m.yes_price}, NO={m.no_price}, end={m.end_date}")

        # Search for "5 minute" / "BTC" in titles
        print(f"\n--- Searching for crypto/short-term keywords ---")
        keywords = ["5 minute", "5-minute", "5min", "Bitcoin Up", "BTC Up", "ETH Up", "next 5"]
        for kw in keywords:
            matches = [(e, m) for e in events for m in e.markets if kw.lower() in m.question.lower()]
            print(f"  '{kw}': {len(matches)} matches")
            for e, m in matches[:2]:
                print(f"    {m.question[:80]}")


if __name__ == "__main__":
    asyncio.run(main())
