"""Binance 1-minute OHLCV fetcher with parquet cache.

Uses ccxt when available; falls back to the public REST endpoint otherwise
so the package is usable in constrained environments. All data is stored
in the cache directory as ``binance_{symbol}_{timeframe}.parquet`` and
incrementally appended on subsequent fetches.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


@dataclass
class BinanceClient:
    cache_dir: Path
    symbol: str = "BTC/USDT"
    timeframe: str = "1m"
    max_retries: int = 4
    timeout_s: float = 20.0

    def __post_init__(self) -> None:
        self.cache_dir = Path(self.cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ cache
    @property
    def cache_path(self) -> Path:
        safe_symbol = self.symbol.replace("/", "").lower()
        return self.cache_dir / f"binance_{safe_symbol}_{self.timeframe}.parquet"

    def load_cached(self) -> pd.DataFrame:
        if not self.cache_path.exists():
            return _empty_frame()
        try:
            df = pd.read_parquet(self.cache_path)
        except Exception as exc:
            logger.warning("cache read failed (%s); starting fresh", exc)
            return _empty_frame()
        return _ensure_schema(df)

    def save_cache(self, df: pd.DataFrame) -> None:
        df = _ensure_schema(df)
        try:
            df.to_parquet(self.cache_path, index=True)
        except Exception as exc:  # pyarrow missing, etc.
            logger.warning("parquet write failed (%s); falling back to csv", exc)
            df.to_csv(self.cache_path.with_suffix(".csv"))

    # ------------------------------------------------------------------ fetch
    def fetch_ohlcv(
        self,
        start_ms: int,
        end_ms: int,
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """Return 1m bars in ``[start_ms, end_ms]`` (inclusive on both ends).

        Cached bars are served directly; missing ranges are pulled from
        the exchange and merged back into the cache.
        """
        cached = self.load_cached() if use_cache else _empty_frame()
        need = _missing_ranges(cached, start_ms, end_ms, self._bar_ms())
        if not need:
            return _slice(cached, start_ms, end_ms)

        fetched_parts: list[pd.DataFrame] = [cached] if not cached.empty else []
        for lo, hi in need:
            logger.info("fetching %s %s bars %s -> %s", self.symbol, self.timeframe, lo, hi)
            fetched_parts.append(self._download(lo, hi))
        merged = _merge(fetched_parts)
        if use_cache:
            self.save_cache(merged)
        return _slice(merged, start_ms, end_ms)

    # ------------------------------------------------------------------ internal
    def _bar_ms(self) -> int:
        # Only 1m is used in practice, but keep the mapping generic.
        unit = self.timeframe[-1]
        qty = int(self.timeframe[:-1])
        mult = {"m": 60_000, "h": 3_600_000, "d": 86_400_000}[unit]
        return qty * mult

    def _download(self, start_ms: int, end_ms: int) -> pd.DataFrame:
        try:
            import ccxt  # type: ignore
        except ImportError:
            return self._download_rest(start_ms, end_ms)

        ex = ccxt.binance({"enableRateLimit": True, "timeout": int(self.timeout_s * 1000)})
        bar_ms = self._bar_ms()
        out: list[list[float]] = []
        cursor = start_ms
        while cursor <= end_ms:
            for attempt in range(self.max_retries):
                try:
                    chunk = ex.fetch_ohlcv(
                        self.symbol, timeframe=self.timeframe, since=cursor, limit=1000
                    )
                    break
                except Exception as exc:
                    backoff = 2 ** attempt
                    logger.warning(
                        "ccxt fetch failed (attempt %d/%d): %s; retrying in %ds",
                        attempt + 1,
                        self.max_retries,
                        exc,
                        backoff,
                    )
                    time.sleep(backoff)
            else:
                raise RuntimeError("ccxt fetch exhausted retries")
            if not chunk:
                break
            out.extend(chunk)
            cursor = chunk[-1][0] + bar_ms
            if len(chunk) < 1000:
                break
        return _frame_from_rows(out)

    def _download_rest(self, start_ms: int, end_ms: int) -> pd.DataFrame:
        import urllib.parse
        import urllib.request
        import json

        bar_ms = self._bar_ms()
        base = "https://api.binance.com/api/v3/klines"
        rest_symbol = self.symbol.replace("/", "")
        out: list[list[float]] = []
        cursor = start_ms
        while cursor <= end_ms:
            params = {
                "symbol": rest_symbol,
                "interval": self.timeframe,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": 1000,
            }
            url = f"{base}?{urllib.parse.urlencode(params)}"
            for attempt in range(self.max_retries):
                try:
                    with urllib.request.urlopen(url, timeout=self.timeout_s) as resp:
                        raw = json.loads(resp.read())
                    break
                except Exception as exc:
                    backoff = 2 ** attempt
                    logger.warning("REST fetch failed (%s); retry in %ds", exc, backoff)
                    time.sleep(backoff)
            else:
                raise RuntimeError("REST fetch exhausted retries")
            if not raw:
                break
            for row in raw:
                out.append([row[0], float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])])
            cursor = raw[-1][0] + bar_ms
            if len(raw) < 1000:
                break
        return _frame_from_rows(out)


# ---------------------------------------------------------------------------
# Pure helpers (no I/O; easy to test)
# ---------------------------------------------------------------------------


def _empty_frame() -> pd.DataFrame:
    idx = pd.DatetimeIndex([], tz="UTC", name="timestamp")
    return pd.DataFrame(
        {c: pd.Series(dtype="float64") for c in ("open", "high", "low", "close", "volume")},
        index=idx,
    )


def _frame_from_rows(rows: list) -> pd.DataFrame:
    if not rows:
        return _empty_frame()
    df = pd.DataFrame(rows, columns=_COLUMNS)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("timestamp").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df


def _ensure_schema(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return _empty_frame()
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df.sort_index()


def _merge(parts: list[pd.DataFrame]) -> pd.DataFrame:
    non_empty = [p for p in parts if not p.empty]
    if not non_empty:
        return _empty_frame()
    merged = pd.concat(non_empty).sort_index()
    merged = merged[~merged.index.duplicated(keep="last")]
    return merged


def _slice(df: pd.DataFrame, start_ms: int, end_ms: int) -> pd.DataFrame:
    if df.empty:
        return df
    start = pd.Timestamp(start_ms, unit="ms", tz="UTC")
    end = pd.Timestamp(end_ms, unit="ms", tz="UTC")
    return df.loc[start:end]


def _missing_ranges(
    cached: pd.DataFrame, start_ms: int, end_ms: int, bar_ms: int
) -> list[tuple[int, int]]:
    """Compute which (start, end) ms ranges are NOT in cache.

    Keeps it simple: treat any gap >= 2 bars as missing; inside-gap fetch
    requests are cheap relative to API latency.
    """
    if cached.empty:
        return [(start_ms, end_ms)]
    cached_ms = (cached.index.view("int64") // 1_000_000).astype("int64")
    # Restrict attention to the requested window.
    mask = (cached_ms >= start_ms) & (cached_ms <= end_ms)
    present = cached_ms[mask]
    if len(present) == 0:
        return [(start_ms, end_ms)]
    gaps: list[tuple[int, int]] = []
    if present[0] > start_ms:
        gaps.append((start_ms, int(present[0]) - bar_ms))
    prev = int(present[0])
    for t in present[1:]:
        t = int(t)
        if t - prev > bar_ms:
            gaps.append((prev + bar_ms, t - bar_ms))
        prev = t
    if prev < end_ms:
        gaps.append((prev + bar_ms, end_ms))
    return gaps
