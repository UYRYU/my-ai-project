"""
Generate realistic sample OHLCV data for multiple symbols.
============================================================
Used for backtesting when Bitget API is unavailable.
Each symbol has realistic price ranges, volatility, and correlation with BTC.

Usage:
    python -m btc_trend_bot.generate_multisymbol_data
    python -m btc_trend_bot.generate_multisymbol_data --symbols ETHUSDT,XRPUSDT
    python -m btc_trend_bot.generate_multisymbol_data --days 730
"""

import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger


# Realistic coin profiles (approximate 2023-2025 characteristics)
COIN_PROFILES = {
    "BTCUSDT": {
        "start_price": 16500,
        "volatility": 0.015,
        "drift_bull": 0.00030,
        "drift_bear": -0.00015,
        "drift_sideways": 0.00005,
        "volume_base": 500,
        "volume_mult": 50000,
        "min_price": 15000,
        "btc_corr": 1.0,  # self-correlation
    },
    "ETHUSDT": {
        "start_price": 1200,
        "volatility": 0.018,
        "drift_bull": 0.00035,
        "drift_bear": -0.00020,
        "drift_sideways": 0.00003,
        "volume_base": 3000,
        "volume_mult": 300000,
        "min_price": 800,
        "btc_corr": 0.85,
    },
    "XRPUSDT": {
        "start_price": 0.35,
        "volatility": 0.022,
        "drift_bull": 0.00040,
        "drift_bear": -0.00025,
        "drift_sideways": 0.00002,
        "volume_base": 50_000_000,
        "volume_mult": 5_000_000_000,
        "min_price": 0.20,
        "btc_corr": 0.70,
    },
    "DOGEUSDT": {
        "start_price": 0.07,
        "volatility": 0.025,
        "drift_bull": 0.00050,
        "drift_bear": -0.00030,
        "drift_sideways": 0.00001,
        "volume_base": 200_000_000,
        "volume_mult": 20_000_000_000,
        "min_price": 0.05,
        "btc_corr": 0.60,
    },
    "SOLUSDT": {
        "start_price": 12.0,
        "volatility": 0.025,
        "drift_bull": 0.00055,
        "drift_bear": -0.00025,
        "drift_sideways": 0.00004,
        "volume_base": 5_000_000,
        "volume_mult": 500_000_000,
        "min_price": 8.0,
        "btc_corr": 0.75,
    },
}


def generate_btc_returns(hours: int, seed: int = 42) -> np.ndarray:
    """Generate BTC return series with realistic regime switches."""
    rng = np.random.RandomState(seed)
    returns = np.zeros(hours)
    profile = COIN_PROFILES["BTCUSDT"]

    for i in range(hours):
        cycle_pos = (i / hours) * 4
        if cycle_pos < 1.0:      # Bull
            drift = profile["drift_bull"]
            vol = profile["volatility"]
        elif cycle_pos < 1.5:    # Correction
            drift = profile["drift_bear"]
            vol = profile["volatility"] * 1.3
        elif cycle_pos < 2.2:    # Sideways
            drift = profile["drift_sideways"]
            vol = profile["volatility"] * 0.7
        elif cycle_pos < 3.2:    # Bull 2
            drift = profile["drift_bull"] * 1.2
            vol = profile["volatility"] * 1.1
        else:                    # Bear
            drift = profile["drift_bear"]
            vol = profile["volatility"] * 1.2

        returns[i] = drift + vol * rng.randn()

    return returns


def generate_coin_data(
    symbol: str,
    btc_returns: np.ndarray,
    hours: int,
    start_date: str = "2023-01-01",
    seed: int = 42,
) -> pd.DataFrame:
    """Generate OHLCV data for a single coin, correlated with BTC."""
    profile = COIN_PROFILES[symbol]
    rng = np.random.RandomState(seed + hash(symbol) % 10000)

    dates = pd.date_range(start_date, periods=hours, freq="1h", tz="UTC")
    price = profile["start_price"]
    prices = []
    volumes = []

    corr = profile["btc_corr"]

    for i in range(hours):
        cycle_pos = (i / hours) * 4
        if cycle_pos < 1.0:
            drift = profile["drift_bull"]
            vol = profile["volatility"]
        elif cycle_pos < 1.5:
            drift = profile["drift_bear"]
            vol = profile["volatility"] * 1.3
        elif cycle_pos < 2.2:
            drift = profile["drift_sideways"]
            vol = profile["volatility"] * 0.7
        elif cycle_pos < 3.2:
            drift = profile["drift_bull"] * 1.2
            vol = profile["volatility"] * 1.1
        else:
            drift = profile["drift_bear"]
            vol = profile["volatility"] * 1.2

        # Correlated with BTC + idiosyncratic noise
        idio = rng.randn()
        btc_component = btc_returns[i] if i < len(btc_returns) else 0
        ret = drift + vol * (corr * btc_component / 0.015 * vol + (1 - corr) * idio)

        price *= (1 + ret)
        price = max(price, profile["min_price"])
        prices.append(price)

        base_vol = profile["volume_base"] + abs(ret) * profile["volume_mult"]
        volumes.append(base_vol * (1 + 0.3 * rng.rand()))

    close = np.array(prices)
    open_ = np.roll(close, 1)
    open_[0] = close[0]

    bar_max = np.maximum(open_, close)
    bar_min = np.minimum(open_, close)
    high = bar_max * (1 + np.abs(rng.randn(hours)) * 0.003)
    low = bar_min * (1 - np.abs(rng.randn(hours)) * 0.003)

    df = pd.DataFrame({
        "datetime": dates,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volumes,
    })

    return df


def generate_all(
    symbols: list[str] | None = None,
    days: int = 365 * 2,
    start_date: str = "2023-01-01",
    output_dir: str | None = None,
) -> dict[str, str]:
    """Generate sample data for all symbols.

    Returns dict of symbol -> file path.
    """
    if symbols is None:
        symbols = list(COIN_PROFILES.keys())

    if output_dir is None:
        output_dir = str(Path(__file__).parent / "data" / "raw")

    os.makedirs(output_dir, exist_ok=True)
    hours = days * 24

    # Generate BTC returns first (other coins correlate with this)
    btc_returns = generate_btc_returns(hours)

    paths = {}
    for symbol in symbols:
        if symbol not in COIN_PROFILES:
            logger.warning(f"No profile for {symbol}, skipping")
            continue

        logger.info(f"Generating {symbol} data: {hours} bars ({days} days)")
        df = generate_coin_data(symbol, btc_returns, hours, start_date)

        filepath = os.path.join(output_dir, f"{symbol}_1h.csv")
        df.to_csv(filepath, index=False)
        logger.info(f"Saved: {filepath} ({len(df)} rows)")
        paths[symbol] = filepath

    return paths


def main():
    logger.remove()
    logger.add(sys.stderr, level="INFO",
               format="<green>{time:HH:mm:ss}</green> | <level>{level:7s}</level> | {message}")

    parser = argparse.ArgumentParser(description="Generate multi-symbol sample data")
    parser.add_argument("--symbols", type=str, default=None,
                        help="Comma-separated symbols (default: all 5)")
    parser.add_argument("--days", type=int, default=730,
                        help="Number of days of data")
    parser.add_argument("--start", type=str, default="2023-01-01")
    parser.add_argument("--output-dir", type=str, default=None)
    args = parser.parse_args()

    symbols = args.symbols.split(",") if args.symbols else None
    paths = generate_all(symbols, args.days, args.start, args.output_dir)

    logger.info(f"\nGenerated data for {len(paths)} symbols:")
    for sym, path in paths.items():
        logger.info(f"  {sym}: {path}")


if __name__ == "__main__":
    main()
