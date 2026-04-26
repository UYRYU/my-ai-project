"""Bitget の公開 K線 API からヒストリカルを取得して CSV 保存."""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd
import requests


GRANULARITY = {
    "1m": "1m", "5m": "5m", "15m": "15m", "1h": "1H", "4h": "4H", "1d": "1D",
}
# Bitget V2 USDT-M perpetual public endpoint (no auth)
BASE = "https://api.bitget.com/api/v2/mix/market/history-candles"


def fetch(symbol: str, granularity: str, start_ms: int, end_ms: int,
          product_type: str = "usdt-futures") -> pd.DataFrame:
    """Fetch klines [start_ms, end_ms). Returns DataFrame with OHLCV (UTC)."""
    g = GRANULARITY.get(granularity, granularity)
    out: list[list] = []
    cursor_end = end_ms
    minute_ms = {"1m": 60_000, "5m": 300_000, "15m": 900_000,
                 "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}[granularity]
    limit = 200

    while True:
        params = dict(symbol=symbol, granularity=g, productType=product_type,
                      endTime=str(cursor_end), limit=str(limit))
        r = requests.get(BASE, params=params, timeout=15)
        r.raise_for_status()
        data = r.json().get("data") or []
        if not data:
            break
        # data: oldest -> newest in this batch
        batch = [[int(x[0]), float(x[1]), float(x[2]), float(x[3]),
                  float(x[4]), float(x[5])] for x in data]
        out = batch + out
        oldest = batch[0][0]
        if oldest <= start_ms:
            break
        cursor_end = oldest - 1
        time.sleep(0.15)

    df = pd.DataFrame(out, columns=["ts", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    df = df[df["ts"] >= start_ms]
    df["time"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.set_index("time")[["open", "high", "low", "close", "volume"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--tf", default="5m", choices=list(GRANULARITY.keys()))
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--out", default="data/btcusdt_5m.csv")
    args = ap.parse_args()

    end = int(time.time() * 1000)
    start = end - args.days * 86_400_000
    print(f"Fetch {args.symbol} {args.tf} {args.days}d ...")
    df = fetch(args.symbol, args.tf, start, end)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out)
    print(f"Saved {len(df)} rows -> {args.out}")
    print(df.head(2))
    print(df.tail(2))


if __name__ == "__main__":
    main()
