"""
Extract bull-run periods from BTCUSDT historical OHLCV data.

A bull run is defined as a sustained period where price trades above the
200-period EMA, meets a minimum duration, and achieves a minimum return.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

from btc_trend_bot.data_loader import DataLoader
from btc_trend_bot.indicators.trend import calc_ema

# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------
_DEFAULTS: dict = {
    "ema_period": 200,
    "min_duration_days": 30,
    "min_return_pct": 20.0,
    "ema_above_ratio": 0.7,
    "merge_gap_days": 5,
}


class BullRunExtractor:
    """Identify and characterise bull-run periods from OHLCV data.

    Parameters
    ----------
    config : dict
        Optional overrides for extraction parameters.  Missing keys are
        filled from built-in defaults.
    """

    def __init__(self, config: dict | None = None) -> None:
        cfg = dict(_DEFAULTS)
        if config:
            cfg.update(config)

        self.ema_period: int = int(cfg["ema_period"])
        self.min_duration_days: int = int(cfg["min_duration_days"])
        self.min_return_pct: float = float(cfg["min_return_pct"])
        self.ema_above_ratio: float = float(cfg["ema_above_ratio"])
        self.merge_gap_days: int = int(cfg["merge_gap_days"])

        logger.info(
            "BullRunExtractor initialised: ema={}, min_days={}, min_ret={:.1f}%, "
            "ema_ratio={:.2f}, merge_gap={}d",
            self.ema_period,
            self.min_duration_days,
            self.min_return_pct,
            self.ema_above_ratio,
            self.merge_gap_days,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self, df: pd.DataFrame) -> pd.DataFrame:
        """Extract bull-run periods from an OHLCV DataFrame.

        Steps
        -----
        1. Calculate 200-period EMA.
        2. Identify contiguous periods where close > EMA.
        3. Merge adjacent above-EMA periods separated by < ``merge_gap_days``.
        4. Filter by minimum duration.
        5. Filter by minimum return.
        6. Compute per-period statistics.

        Returns
        -------
        pd.DataFrame
            Columns: start_date, end_date, duration_days, return_pct,
            max_drawdown_during, avg_price, ema200_above_ratio.
        """
        logger.info("Extracting bull runs from {} rows of data", len(df))

        # Step 1 – EMA
        ema = calc_ema(df, column="close", period=self.ema_period)

        # Step 2 – above-EMA mask and contiguous segments
        above_ema = df["close"] > ema
        segments = self._identify_segments(df, above_ema)

        if segments.empty:
            logger.warning("No above-EMA segments found")
            return self._empty_result()

        logger.info("Found {} raw above-EMA segments", len(segments))

        # Step 3 – merge close segments
        segments = self._merge_close_segments(segments)
        logger.info("After merging close segments: {} segments", len(segments))

        # Step 4 – minimum duration filter
        segments = segments[
            segments["duration_days"] >= self.min_duration_days
        ].reset_index(drop=True)
        logger.info("After min-duration filter ({}d): {} segments", self.min_duration_days, len(segments))

        if segments.empty:
            logger.warning("No segments survived the duration filter")
            return self._empty_result()

        # Step 5 & 6 – compute stats (return, drawdown, etc.) and filter by return
        bull_runs = self._compute_stats(df, ema, segments)
        bull_runs = bull_runs[
            bull_runs["return_pct"] >= self.min_return_pct
        ].reset_index(drop=True)
        logger.info(
            "After min-return filter ({:.1f}%): {} bull runs",
            self.min_return_pct,
            len(bull_runs),
        )

        return bull_runs

    def extract_pre_bull_periods(
        self,
        df: pd.DataFrame,
        bull_runs: pd.DataFrame,
        lookback_days: int = 30,
    ) -> pd.DataFrame:
        """Extract the period just before each bull run starts.

        Useful for analysing early-entry signals.

        Parameters
        ----------
        df : pd.DataFrame
            Full OHLCV data with DatetimeIndex.
        bull_runs : pd.DataFrame
            Output of :meth:`extract`.
        lookback_days : int
            Number of calendar days before each bull-run start to capture.

        Returns
        -------
        pd.DataFrame
            Concatenated OHLCV slices with an extra ``bull_run_id`` column
            indicating which upcoming bull run the rows precede.
        """
        if bull_runs.empty:
            logger.warning("No bull runs provided; returning empty DataFrame")
            return pd.DataFrame()

        lookback_td = pd.Timedelta(days=lookback_days)
        slices: list[pd.DataFrame] = []

        for idx, row in bull_runs.iterrows():
            start = pd.Timestamp(row["start_date"])
            period_start = start - lookback_td
            mask = (df.index >= period_start) & (df.index < start)
            chunk = df.loc[mask].copy()
            if not chunk.empty:
                chunk["bull_run_id"] = int(idx)
                slices.append(chunk)

        if not slices:
            logger.warning("No pre-bull data found for any bull run")
            return pd.DataFrame()

        result = pd.concat(slices)
        logger.info(
            "Extracted {} pre-bull rows across {} runs (lookback={}d)",
            len(result),
            len(slices),
            lookback_days,
        )
        return result

    def save(self, bull_runs: pd.DataFrame, output_path: str) -> None:
        """Save bull-run summary to CSV.

        Parameters
        ----------
        bull_runs : pd.DataFrame
            Output of :meth:`extract`.
        output_path : str
            Destination file path.  Parent directories are created if needed.
        """
        out = Path(output_path)
        os.makedirs(out.parent, exist_ok=True)
        bull_runs.to_csv(out, index=False)
        logger.info("Saved {} bull runs to {}", len(bull_runs), out)

    def filter_data_to_bull_runs(
        self, df: pd.DataFrame, bull_runs: pd.DataFrame
    ) -> pd.DataFrame:
        """Filter original OHLCV data to only bull-run periods.

        Parameters
        ----------
        df : pd.DataFrame
            Full OHLCV data with DatetimeIndex.
        bull_runs : pd.DataFrame
            Output of :meth:`extract`.

        Returns
        -------
        pd.DataFrame
            Subset of *df* that falls within at least one bull-run window,
            with an additional ``bull_run_id`` column.
        """
        if bull_runs.empty:
            logger.warning("No bull runs provided; returning empty DataFrame")
            return pd.DataFrame()

        slices: list[pd.DataFrame] = []
        for idx, row in bull_runs.iterrows():
            start = pd.Timestamp(row["start_date"])
            end = pd.Timestamp(row["end_date"])
            mask = (df.index >= start) & (df.index <= end)
            chunk = df.loc[mask].copy()
            if not chunk.empty:
                chunk["bull_run_id"] = int(idx)
                slices.append(chunk)

        if not slices:
            logger.warning("No data matched any bull-run period")
            return pd.DataFrame()

        result = pd.concat(slices)
        logger.info(
            "Filtered to {} rows across {} bull runs",
            len(result),
            len(slices),
        )
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _empty_result() -> pd.DataFrame:
        """Return an empty DataFrame with the expected result schema."""
        return pd.DataFrame(
            columns=[
                "start_date",
                "end_date",
                "duration_days",
                "return_pct",
                "max_drawdown_during",
                "avg_price",
                "ema200_above_ratio",
            ]
        )

    @staticmethod
    def _identify_segments(
        df: pd.DataFrame, mask: pd.Series
    ) -> pd.DataFrame:
        """Find contiguous True-segments in *mask* and return their boundaries.

        Returns a DataFrame with columns: start_date, end_date, duration_days.
        """
        # Detect edges: 0->1 starts a segment, 1->0 ends it
        mask_int = mask.astype(int)
        diff = mask_int.diff().fillna(mask_int.iloc[0])

        starts = df.index[diff == 1].tolist()
        ends: list[pd.Timestamp] = []

        for s in starts:
            # Slice from the start onwards and find first False
            after_start = mask.loc[s:]
            false_after = after_start[~after_start]
            if false_after.empty:
                # Segment runs to the end of the data
                ends.append(df.index[-1])
            else:
                # The bar just before the first False is the segment end
                end_idx = df.index.get_loc(false_after.index[0]) - 1
                ends.append(df.index[end_idx])

        if not starts:
            return pd.DataFrame(columns=["start_date", "end_date", "duration_days"])

        segments = pd.DataFrame({"start_date": starts, "end_date": ends})
        segments["duration_days"] = (
            (segments["end_date"] - segments["start_date"]).dt.total_seconds()
            / 86400.0
        )
        return segments

    def _merge_close_segments(self, segments: pd.DataFrame) -> pd.DataFrame:
        """Merge segments whose gap is less than ``merge_gap_days`` days."""
        if len(segments) <= 1:
            return segments

        gap_threshold = pd.Timedelta(days=self.merge_gap_days)
        merged_starts: list[pd.Timestamp] = [segments.iloc[0]["start_date"]]
        merged_ends: list[pd.Timestamp] = [segments.iloc[0]["end_date"]]

        for i in range(1, len(segments)):
            gap = segments.iloc[i]["start_date"] - merged_ends[-1]
            if gap <= gap_threshold:
                # Extend current merged segment
                merged_ends[-1] = segments.iloc[i]["end_date"]
            else:
                merged_starts.append(segments.iloc[i]["start_date"])
                merged_ends.append(segments.iloc[i]["end_date"])

        merged = pd.DataFrame({"start_date": merged_starts, "end_date": merged_ends})
        merged["duration_days"] = (
            (merged["end_date"] - merged["start_date"]).dt.total_seconds() / 86400.0
        )
        return merged

    def _compute_stats(
        self,
        df: pd.DataFrame,
        ema: pd.Series,
        segments: pd.DataFrame,
    ) -> pd.DataFrame:
        """Compute per-segment statistics.

        Adds columns: return_pct, max_drawdown_during, avg_price,
        ema200_above_ratio.
        """
        records: list[dict] = []

        for _, seg in segments.iterrows():
            start = seg["start_date"]
            end = seg["end_date"]
            chunk = df.loc[start:end]

            if chunk.empty:
                continue

            entry_price = chunk["close"].iloc[0]
            exit_price = chunk["close"].iloc[-1]
            return_pct = ((exit_price - entry_price) / entry_price) * 100.0

            # Max drawdown within the period
            cummax = chunk["close"].cummax()
            drawdown = (chunk["close"] - cummax) / cummax * 100.0
            max_dd = drawdown.min()

            avg_price = chunk["close"].mean()

            # Ratio of bars where close > EMA200
            ema_chunk = ema.loc[start:end]
            if len(ema_chunk) > 0:
                above_ratio = (chunk["close"] > ema_chunk).sum() / len(ema_chunk)
            else:
                above_ratio = np.nan

            records.append(
                {
                    "start_date": start,
                    "end_date": end,
                    "duration_days": seg["duration_days"],
                    "return_pct": round(return_pct, 2),
                    "max_drawdown_during": round(max_dd, 2),
                    "avg_price": round(avg_price, 2),
                    "ema200_above_ratio": round(above_ratio, 4),
                }
            )

        if not records:
            return self._empty_result()

        return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logger.remove()
    logger.add(sys.stderr, level="INFO")

    # 1. Load data
    data_path = "data/raw/BTCUSDT_1h.csv"
    logger.info("Loading BTCUSDT 1h data from {}", data_path)
    loader = DataLoader(data_dir="data/raw")
    df = loader.load_csv(data_path)

    # 2. Extract bull runs
    config = {
        "min_duration_days": 30,
        "min_return_pct": 20.0,
        "ema_above_ratio": 0.7,
    }
    extractor = BullRunExtractor(config=config)
    bull_runs = extractor.extract(df)

    # 3. Save results
    output_path = "data/processed/bull_runs.csv"
    extractor.save(bull_runs, output_path)

    # 4. Print summary
    print("\n" + "=" * 70)
    print("BTCUSDT Bull Run Extraction Summary")
    print("=" * 70)
    print(f"Data range    : {df.index[0]} -> {df.index[-1]}")
    print(f"Total bars    : {len(df):,}")
    print(f"Bull runs found: {len(bull_runs)}")
    print("-" * 70)

    if not bull_runs.empty:
        for i, row in bull_runs.iterrows():
            print(
                f"  #{i + 1}  {row['start_date']}  ->  {row['end_date']}  "
                f"| {row['duration_days']:.0f}d  "
                f"| ret {row['return_pct']:+.1f}%  "
                f"| dd {row['max_drawdown_during']:.1f}%  "
                f"| avg ${row['avg_price']:,.0f}  "
                f"| EMA200 ratio {row['ema200_above_ratio']:.2f}"
            )
        print("-" * 70)
        print(f"  Avg duration  : {bull_runs['duration_days'].mean():.1f} days")
        print(f"  Avg return    : {bull_runs['return_pct'].mean():.1f}%")
        print(f"  Avg max DD    : {bull_runs['max_drawdown_during'].mean():.1f}%")
        print(f"  Avg EMA200 %  : {bull_runs['ema200_above_ratio'].mean():.2%}")
    else:
        print("  No bull runs detected with current parameters.")

    print("=" * 70)
    print(f"\nResults saved to {output_path}")
