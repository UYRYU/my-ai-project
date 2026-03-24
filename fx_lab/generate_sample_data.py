"""サンプルOHLCデータを生成するユーティリティ

実行: python generate_sample_data.py
"""

import os
import numpy as np
import pandas as pd


def generate_ohlc(symbol: str, timeframe: str, rows: int = 5000,
                  base_price: float = 150.0, volatility: float = 0.05) -> pd.DataFrame:
    """ランダムウォークベースのサンプルOHLCデータを生成"""
    np.random.seed(hash(f"{symbol}_{timeframe}") % (2**31))

    if timeframe == "M1":
        freq = "1min"
    elif timeframe == "M5":
        freq = "5min"
    else:
        freq = "1min"

    timestamps = pd.date_range(start="2025-01-02 09:00:00", periods=rows, freq=freq)

    prices = [base_price]
    for _ in range(rows - 1):
        change = np.random.normal(0, volatility)
        prices.append(prices[-1] + change)

    data = []
    for i, ts in enumerate(timestamps):
        p = prices[i]
        noise = np.random.uniform(0.01, volatility * 2, 3)
        o = p + np.random.normal(0, volatility * 0.5)
        h = max(p, o) + noise[0]
        l = min(p, o) - noise[1]
        c = p
        v = np.random.randint(50, 500)
        data.append([ts, round(o, 3), round(h, 3), round(l, 3), round(c, 3), v])

    return pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close", "volume"])


def main():
    output_dir = os.path.join(os.path.dirname(__file__), "data", "raw")
    os.makedirs(output_dir, exist_ok=True)

    configs = [
        ("USDJPY", "M1", 150.0, 0.05),
        ("USDJPY", "M5", 150.0, 0.08),
        ("EURJPY", "M1", 162.0, 0.06),
        ("EURJPY", "M5", 162.0, 0.10),
        ("GBPJPY", "M1", 188.0, 0.07),
        ("GBPJPY", "M5", 188.0, 0.12),
    ]

    for symbol, tf, base, vol in configs:
        df = generate_ohlc(symbol, tf, rows=5000, base_price=base, volatility=vol)
        filepath = os.path.join(output_dir, f"{symbol}_{tf}.csv")
        df.to_csv(filepath, index=False)
        print(f"生成: {filepath} ({len(df)} rows)")


if __name__ == "__main__":
    main()
