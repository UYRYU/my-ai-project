"""
OHLCV Data Loader for BTCUSDT
Handles CSV loading, multi-timeframe, quality checks, and preprocessing.
"""

import os
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger


class DataLoader:
    """Load and preprocess BTCUSDT OHLCV data from CSV files."""

    REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume"]
    VALID_TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d", "1w"]

    def __init__(self, data_dir: str = "data/raw", timezone: str = "UTC"):
        self.data_dir = Path(data_dir)
        self.timezone = timezone

    def load_csv(
        self,
        filepath: str,
        timeframe: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """Load OHLCV data from a CSV file.

        Expects columns: timestamp/date/datetime, open, high, low, close, volume
        """
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"Data file not found: {filepath}")

        logger.info(f"Loading data from {filepath}")
        df = pd.read_csv(filepath)

        # Normalize column names
        df.columns = [c.strip().lower() for c in df.columns]

        # Find datetime column
        dt_col = self._find_datetime_column(df)
        if dt_col is None:
            raise ValueError("No datetime column found. Expected: timestamp, date, datetime, or time")

        df["datetime"] = pd.to_datetime(df[dt_col], utc=True)
        df = df.set_index("datetime").sort_index()

        # Keep only OHLCV
        missing = [c for c in self.REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

        df = df[self.REQUIRED_COLUMNS].copy()
        df = df.astype(float)

        # Quality checks
        df = self._quality_check(df)

        # Date filter
        if start_date:
            df = df[df.index >= pd.Timestamp(start_date, tz="UTC")]
        if end_date:
            df = df[df.index <= pd.Timestamp(end_date, tz="UTC")]

        logger.info(f"Loaded {len(df)} rows from {df.index[0]} to {df.index[-1]}")
        return df

    def load_timeframe(
        self,
        timeframe: str,
        symbol: str = "BTCUSDT",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """Load data for a specific timeframe from the data directory.

        Searches for files matching pattern: {symbol}_{timeframe}.csv
        """
        pattern = f"*{symbol}*{timeframe}*"
        files = list(self.data_dir.glob(pattern))
        if not files:
            # Try case-insensitive
            pattern_lower = f"*{symbol.lower()}*{timeframe}*"
            files = list(self.data_dir.glob(pattern_lower))
        if not files:
            raise FileNotFoundError(
                f"No data file found for {symbol} {timeframe} in {self.data_dir}"
            )

        return self.load_csv(str(files[0]), timeframe, start_date, end_date)

    def resample(self, df: pd.DataFrame, target_tf: str) -> pd.DataFrame:
        """Resample OHLCV data to a higher timeframe."""
        tf_map = {
            "5m": "5min", "15m": "15min", "30m": "30min",
            "1h": "1h", "4h": "4h", "1d": "1D", "1w": "1W",
        }
        if target_tf not in tf_map:
            raise ValueError(f"Unsupported timeframe: {target_tf}")

        freq = tf_map[target_tf]
        resampled = df.resample(freq).agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna()

        logger.info(f"Resampled to {target_tf}: {len(resampled)} bars")
        return resampled

    def _find_datetime_column(self, df: pd.DataFrame) -> Optional[str]:
        """Find the datetime column in the dataframe."""
        candidates = ["datetime", "timestamp", "date", "time", "open_time", "open time"]
        for c in candidates:
            if c in df.columns:
                return c
        # Check if index is datetime
        if pd.api.types.is_datetime64_any_dtype(df.index):
            return None
        # Try first column
        try:
            pd.to_datetime(df.iloc[:, 0])
            return df.columns[0]
        except (ValueError, TypeError):
            return None

    def _quality_check(self, df: pd.DataFrame) -> pd.DataFrame:
        """Run data quality checks and clean issues."""
        initial_len = len(df)

        # Remove duplicates
        dup_count = df.index.duplicated().sum()
        if dup_count > 0:
            logger.warning(f"Removing {dup_count} duplicate timestamps")
            df = df[~df.index.duplicated(keep="last")]

        # Remove rows with NaN
        nan_count = df.isna().any(axis=1).sum()
        if nan_count > 0:
            logger.warning(f"Removing {nan_count} rows with NaN values")
            df = df.dropna()

        # Validate OHLC relationships
        invalid = (
            (df["high"] < df["low"])
            | (df["high"] < df["open"])
            | (df["high"] < df["close"])
            | (df["low"] > df["open"])
            | (df["low"] > df["close"])
        )
        inv_count = invalid.sum()
        if inv_count > 0:
            logger.warning(f"Removing {inv_count} rows with invalid OHLC")
            df = df[~invalid]

        # Remove zero/negative volume
        bad_vol = df["volume"] <= 0
        if bad_vol.sum() > 0:
            logger.warning(f"Removing {bad_vol.sum()} rows with zero/negative volume")
            df = df[~bad_vol]

        # Remove zero price
        zero_price = (df[["open", "high", "low", "close"]] <= 0).any(axis=1)
        if zero_price.sum() > 0:
            logger.warning(f"Removing {zero_price.sum()} rows with zero/negative price")
            df = df[~zero_price]

        removed = initial_len - len(df)
        if removed > 0:
            logger.info(f"Quality check: removed {removed} rows ({removed/initial_len*100:.2f}%)")

        return df


def generate_sample_data(
    output_path: str = "data/raw/BTCUSDT_1h.csv",
    days: int = 365 * 3,
) -> None:
    """Generate synthetic BTCUSDT data for testing.

    Creates data with realistic bull/bear/sideways cycles.
    """
    np.random.seed(42)
    hours = days * 24
    dates = pd.date_range("2021-01-01", periods=hours, freq="1h", tz="UTC")

    # Simulate price with regime changes
    price = 29000.0
    prices = []
    volumes = []

    for i in range(hours):
        # Regime based on position in cycle
        cycle_pos = (i / hours) * 4  # 4 major phases
        if cycle_pos < 1:  # Bull run 1
            drift = 0.0003
            vol = 0.015
        elif cycle_pos < 1.5:  # Correction
            drift = -0.0002
            vol = 0.02
        elif cycle_pos < 2.2:  # Sideways
            drift = 0.00005
            vol = 0.01
        elif cycle_pos < 3.2:  # Bull run 2
            drift = 0.00035
            vol = 0.018
        else:  # Bear
            drift = -0.00015
            vol = 0.02

        ret = drift + vol * np.random.randn()
        price *= (1 + ret)
        price = max(price, 1000)
        prices.append(price)

        base_volume = 500 + abs(ret) * 50000
        volumes.append(base_volume * (1 + 0.3 * np.random.rand()))

    close = np.array(prices)
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    # Ensure high >= max(open, close) and low <= min(open, close)
    bar_max = np.maximum(open_, close)
    bar_min = np.minimum(open_, close)
    high = bar_max * (1 + np.abs(np.random.randn(hours)) * 0.003)
    low = bar_min * (1 - np.abs(np.random.randn(hours)) * 0.003)

    df = pd.DataFrame({
        "datetime": dates,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volumes,
    })

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    df.to_csv(output_path, index=False)
    logger.info(f"Generated sample data: {output_path} ({len(df)} rows)")


if __name__ == "__main__":
    generate_sample_data()
    print("Sample data generated. You can now run backtest.")
