"""OHLCV loader with CSV cache + optional ccxt fallback.

Designed for backtests on BTC/USDT 1h. In this sandbox network egress to
exchange APIs is blocked, so the primary path is the local CSV cache; ccxt
is kept as a fallback for environments with network access.

Resolution order:
1. `data/<symbol_compact>_<tf>.csv` (e.g. `data/BTCUSDT_1h.csv`) if it covers
   the requested period.
2. Local 15m CSV cache (`data/btcusd_15m_*.csv`) resampled to the requested
   timeframe; the resampled result is written to (1) for subsequent calls.
3. ccxt fetch from a public exchange, paginated, then written to (1).
"""

from __future__ import annotations

import glob
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd


CACHE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CACHE_DIR.parent


def _symbol_compact(symbol: str) -> str:
    return symbol.replace("/", "").upper()


def _cache_path(symbol: str, tf: str) -> Path:
    return CACHE_DIR / f"{_symbol_compact(symbol)}_{tf}.csv"


def _read_cache(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    df = pd.read_csv(path, parse_dates=["time"])
    return df.sort_values("time").reset_index(drop=True)


def _covers(df: pd.DataFrame, start: datetime, end: datetime) -> bool:
    if df.empty:
        return False
    first, last = df["time"].iloc[0], df["time"].iloc[-1]
    return first <= start and last >= end - pd.Timedelta(hours=1)


def _slice(df: pd.DataFrame, start: datetime, end: datetime) -> pd.DataFrame:
    mask = (df["time"] >= start) & (df["time"] < end)
    return df.loc[mask].reset_index(drop=True)


def _tf_to_pandas(tf: str) -> str:
    mapping = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min",
               "1h": "1h", "4h": "4h", "1d": "1D"}
    if tf not in mapping:
        raise ValueError(f"Unsupported timeframe: {tf}")
    return mapping[tf]


def _resample(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    rule = _tf_to_pandas(tf)
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in df.columns:
        agg["volume"] = "sum"
    out = (
        df.set_index("time")
        .resample(rule, label="left", closed="left")
        .agg(agg)
        .dropna(subset=["open", "high", "low", "close"])
        .reset_index()
    )
    return out


_QUOTES = ("USDT", "USDC", "BUSD", "USD")


def _split_symbol(symbol: str) -> tuple[str, str]:
    if "/" in symbol:
        base, quote = symbol.split("/", 1)
        return base.upper(), quote.upper()
    sym = symbol.upper()
    for q in _QUOTES:
        if sym.endswith(q):
            return sym[: -len(q)], q
    raise ValueError(f"Cannot parse symbol: {symbol!r}")


def _load_from_15m(symbol: str) -> pd.DataFrame | None:
    """Look for symbol-specific 15m CSV sources to resample from.

    Recognised filename patterns (any of):
        {base.lower()}usd_15m_*.csv     # e.g. btcusd_15m_2022.csv, ethusd_15m_2017.csv
        {base.lower()}usdt_15m_*.csv    # e.g. btcusdt_15m_2022.csv
    """
    base, _ = _split_symbol(symbol)
    patterns = [f"{base.lower()}usd_15m_*.csv",
                f"{base.lower()}usdt_15m_*.csv"]
    files: list[str] = []
    for pat in patterns:
        files.extend(glob.glob(str(CACHE_DIR / pat)))
    files = sorted(set(files))
    if not files:
        return None
    frames = [pd.read_csv(f, parse_dates=["time"]) for f in files]
    df = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["time"])
    return df.sort_values("time").reset_index(drop=True)


def _fetch_via_ccxt(symbol: str, tf: str, start: datetime, end: datetime,
                    exchange_name: str = "binance") -> pd.DataFrame:
    import ccxt  # imported lazily

    ex = getattr(ccxt, exchange_name)({"enableRateLimit": True})
    tf_ms = ex.parse_timeframe(tf) * 1000
    since = int(start.replace(tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = int(end.replace(tzinfo=timezone.utc).timestamp() * 1000)

    rows: list[list] = []
    while since < end_ms:
        batch = ex.fetch_ohlcv(symbol, timeframe=tf, since=since, limit=1000)
        if not batch:
            break
        rows.extend(batch)
        next_since = batch[-1][0] + tf_ms
        if next_since <= since:
            break
        since = next_since

    if not rows:
        raise RuntimeError(f"ccxt returned no data for {symbol} {tf}")

    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["time"] = pd.to_datetime(df["timestamp"], unit="ms")
    return df[["time", "open", "high", "low", "close", "volume"]].drop_duplicates(subset=["time"])


def load_ohlcv(symbol: str, tf: str, start: datetime | str,
               end: datetime | str) -> pd.DataFrame:
    """Return OHLC(V) bars in [start, end). Columns: time, open, high, low, close [, volume]."""
    if isinstance(start, str):
        start = datetime.fromisoformat(start)
    if isinstance(end, str):
        end = datetime.fromisoformat(end)

    cache = _cache_path(symbol, tf)
    cached = _read_cache(cache)
    if cached is not None and _covers(cached, start, end):
        return _slice(cached, start, end)

    raw_15m = _load_from_15m(symbol)
    if raw_15m is not None and _covers(raw_15m, start, end):
        df = _resample(raw_15m, tf) if tf != "15m" else raw_15m
        df.to_csv(cache, index=False)
        return _slice(df, start, end)

    df = _fetch_via_ccxt(symbol, tf, start, end)
    df.to_csv(cache, index=False)
    return _slice(df, start, end)


__all__ = ["load_ohlcv"]
