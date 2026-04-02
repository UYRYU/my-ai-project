"""Bitget public API adapter for fetching market data."""

import os
import time
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
from loguru import logger

from btc_trend_bot.exchange.base import BaseExchange
from btc_trend_bot.exchange.models import ExchangeConfig, Ticker

# Mapping from standard timeframe strings to Bitget v2 granularity values.
GRANULARITY_MAP: dict[str, str] = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1day",
    "1w": "1week",
}

# Approximate duration of one candle in each timeframe (milliseconds).
TIMEFRAME_MS: dict[str, int] = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
    "1w": 604_800_000,
}

MAX_CANDLES_PER_REQUEST = 1000
MAX_RETRIES = 3
RATE_LIMIT_DELAY = 0.1  # seconds between requests


class BitgetPublicClient(BaseExchange):
    """Bitget v2 public REST API client for market data."""

    def __init__(self, config: Optional[ExchangeConfig] = None):
        if config is None:
            config = ExchangeConfig()
        super().__init__(config)
        self._session = requests.Session()
        self._session.headers.update({
            "Content-Type": "application/json",
        })
        self._last_request_ts: float = 0.0
        logger.info(
            "BitgetPublicClient initialised | base_url={}",
            self.config.base_url,
        )

    # ------------------------------------------------------------------
    # Public API: OHLCV
    # ------------------------------------------------------------------

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: Optional[str] = None,
        until: Optional[str] = None,
        limit: int = 1000,
    ) -> pd.DataFrame:
        """Fetch OHLCV candle data from Bitget.

        Args:
            symbol: Trading pair (e.g. "BTCUSDT").
            timeframe: One of 1m, 5m, 15m, 30m, 1h, 4h, 1d, 1w.
            since: ISO-format start datetime (inclusive).
            until: ISO-format end datetime (inclusive).
            limit: Max candles to return (capped at 1000 per request).

        Returns:
            DataFrame with datetime index and columns: open, high, low, close, volume.
        """
        granularity = self._resolve_granularity(timeframe)
        params: dict = {
            "symbol": symbol,
            "granularity": granularity,
            "limit": str(min(limit, MAX_CANDLES_PER_REQUEST)),
        }
        if since is not None:
            start_ms = int(pd.Timestamp(since).timestamp() * 1000)
            params["startTime"] = str(start_ms)
        if until is not None:
            end_ms = int(pd.Timestamp(until).timestamp() * 1000)
            params["endTime"] = str(end_ms)

        data = self._request("/api/v2/spot/market/candles", params)
        candles = data.get("data", [])
        if not candles:
            logger.warning("No candles returned for {} {}", symbol, timeframe)
            return self._empty_ohlcv()

        df = self._parse_candles(candles)
        logger.debug(
            "Fetched {} candles for {} {} | {} -> {}",
            len(df),
            symbol,
            timeframe,
            df.index.min(),
            df.index.max(),
        )
        return df

    def fetch_ohlcv_range(
        self,
        symbol: str,
        timeframe: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """Fetch a full date range with automatic pagination.

        Bitget returns newest candles first, so we paginate backward:
        set endTime, receive up to 1000 candles, then move endTime to the
        oldest timestamp received minus one candle width, and repeat until
        we reach start_date.

        Args:
            symbol: Trading pair (e.g. "BTCUSDT").
            timeframe: Candle timeframe string.
            start_date: ISO-format start date (inclusive).
            end_date: ISO-format end date (inclusive).

        Returns:
            Sorted DataFrame covering the requested range.
        """
        granularity = self._resolve_granularity(timeframe)
        candle_ms = TIMEFRAME_MS[timeframe]

        start_ms = int(pd.Timestamp(start_date).timestamp() * 1000)
        end_ms = int(pd.Timestamp(end_date).timestamp() * 1000)

        all_frames: list[pd.DataFrame] = []
        current_end_ms = end_ms
        total_fetched = 0

        while current_end_ms >= start_ms:
            params: dict = {
                "symbol": symbol,
                "granularity": granularity,
                "endTime": str(current_end_ms),
                "limit": str(MAX_CANDLES_PER_REQUEST),
            }

            data = self._request("/api/v2/spot/market/candles", params)
            candles = data.get("data", [])

            if not candles:
                logger.debug("No more candles returned, stopping pagination")
                break

            df = self._parse_candles(candles)
            all_frames.append(df)
            total_fetched += len(df)

            oldest_ts_ms = int(df.index.min().timestamp() * 1000)

            if oldest_ts_ms <= start_ms:
                logger.debug("Reached start_date boundary, stopping pagination")
                break

            # Move the window: set endTime to one candle before the oldest received
            current_end_ms = oldest_ts_ms - candle_ms

            if len(candles) < MAX_CANDLES_PER_REQUEST:
                logger.debug(
                    "Received fewer candles than limit ({} < {}), stopping",
                    len(candles),
                    MAX_CANDLES_PER_REQUEST,
                )
                break

        if not all_frames:
            logger.warning(
                "No data fetched for {} {} from {} to {}",
                symbol,
                timeframe,
                start_date,
                end_date,
            )
            return self._empty_ohlcv()

        combined = pd.concat(all_frames)
        combined = combined[~combined.index.duplicated(keep="first")]
        combined.sort_index(inplace=True)

        # Trim to requested range
        mask = (combined.index >= pd.Timestamp(start_date)) & (
            combined.index <= pd.Timestamp(end_date)
        )
        combined = combined.loc[mask]

        logger.info(
            "Fetched {} total candles for {} {} | {} -> {}",
            len(combined),
            symbol,
            timeframe,
            start_date,
            end_date,
        )
        return combined

    def download_and_save(
        self,
        symbol: str,
        timeframe: str,
        start_date: str,
        end_date: str,
        output_dir: str = "data/raw",
    ) -> str:
        """Download OHLCV data and save to CSV.

        If the file already exists, only new data after the last stored
        timestamp is fetched and appended.

        Args:
            symbol: Trading pair.
            timeframe: Candle timeframe.
            start_date: ISO start date.
            end_date: ISO end date.
            output_dir: Directory to write CSV files.

        Returns:
            Absolute path to the saved CSV file.
        """
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        filename = f"{symbol}_{timeframe}.csv"
        filepath = out_path / filename

        effective_start = start_date

        if filepath.exists():
            existing = pd.read_csv(
                filepath, index_col=0, parse_dates=True
            )
            if not existing.empty:
                last_ts = existing.index.max()
                logger.info(
                    "Existing data found up to {}, fetching new data after that",
                    last_ts,
                )
                # Start from the next candle after the last one we have
                candle_ms = TIMEFRAME_MS[timeframe]
                new_start_ms = int(last_ts.timestamp() * 1000) + candle_ms
                effective_start = str(
                    pd.Timestamp(new_start_ms, unit="ms", tz="UTC")
                )

                if pd.Timestamp(effective_start) > pd.Timestamp(end_date):
                    logger.info("Data already up to date, nothing to fetch")
                    return str(filepath.resolve())

                new_data = self.fetch_ohlcv_range(
                    symbol, timeframe, effective_start, end_date
                )
                if not new_data.empty:
                    combined = pd.concat([existing, new_data])
                    combined = combined[~combined.index.duplicated(keep="last")]
                    combined.sort_index(inplace=True)
                    combined.to_csv(filepath)
                    logger.info(
                        "Appended {} new candles -> {} total | {}",
                        len(new_data),
                        len(combined),
                        filepath,
                    )
                else:
                    logger.info("No new candles to append")
                return str(filepath.resolve())

        df = self.fetch_ohlcv_range(symbol, timeframe, start_date, end_date)
        if not df.empty:
            df.to_csv(filepath)
            logger.info("Saved {} candles to {}", len(df), filepath)
        else:
            logger.warning("No data to save for {} {}", symbol, timeframe)

        return str(filepath.resolve())

    # ------------------------------------------------------------------
    # Public API: Ticker
    # ------------------------------------------------------------------

    def fetch_ticker(self, symbol: str) -> Ticker:
        """Fetch current ticker for a symbol.

        Endpoint: GET /api/v2/spot/market/tickers?symbol=<symbol>
        """
        data = self._request(
            "/api/v2/spot/market/tickers", {"symbol": symbol}
        )
        tickers = data.get("data", [])
        if not tickers:
            raise ValueError(f"No ticker data returned for {symbol}")

        t = tickers[0]
        return Ticker(
            symbol=str(t.get("symbol", symbol)),
            last_price=float(t["lastPr"]),
            bid=float(t["bidPr"]),
            ask=float(t["askPr"]),
            volume_24h=float(t["baseVolume"]),
            timestamp=pd.Timestamp.utcnow(),
        )

    # ------------------------------------------------------------------
    # Public API: Server time
    # ------------------------------------------------------------------

    def get_server_time(self) -> pd.Timestamp:
        """Get Bitget server time.

        Endpoint: GET /api/v2/public/time
        """
        data = self._request("/api/v2/public/time")
        server_ts_ms = int(data["data"]["serverTime"])
        return pd.Timestamp(server_ts_ms, unit="ms", tz="UTC")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _request(
        self, endpoint: str, params: Optional[dict] = None
    ) -> dict:
        """Make an HTTP GET request with rate limiting and retry logic.

        Retries up to 3 times with exponential backoff (1s, 2s, 4s)
        on transient failures.
        """
        url = self.config.base_url.rstrip("/") + endpoint

        for attempt in range(1, MAX_RETRIES + 1):
            # Rate-limit enforcement
            elapsed = time.monotonic() - self._last_request_ts
            if elapsed < RATE_LIMIT_DELAY:
                time.sleep(RATE_LIMIT_DELAY - elapsed)

            try:
                self._last_request_ts = time.monotonic()
                response = self._session.get(url, params=params, timeout=30)
                response.raise_for_status()
                body: dict = response.json()

                # Bitget wraps responses: {"code": "00000", "data": ...}
                code = body.get("code", "")
                if code != "00000":
                    msg = body.get("msg", "unknown error")
                    logger.error(
                        "Bitget API error | code={} msg={} endpoint={}",
                        code,
                        msg,
                        endpoint,
                    )
                    raise RuntimeError(
                        f"Bitget API error code={code}: {msg}"
                    )

                return body

            except (requests.RequestException, RuntimeError) as exc:
                backoff = 2 ** (attempt - 1)  # 1s, 2s, 4s
                if attempt < MAX_RETRIES:
                    logger.warning(
                        "Request failed (attempt {}/{}), retrying in {}s: {}",
                        attempt,
                        MAX_RETRIES,
                        backoff,
                        exc,
                    )
                    time.sleep(backoff)
                else:
                    logger.error(
                        "Request failed after {} attempts: {}",
                        MAX_RETRIES,
                        exc,
                    )
                    raise

        # Should never reach here, but satisfy the type checker.
        raise RuntimeError("Unreachable: all retries exhausted")

    @staticmethod
    def _resolve_granularity(timeframe: str) -> str:
        """Convert a standard timeframe string to Bitget granularity."""
        granularity = GRANULARITY_MAP.get(timeframe)
        if granularity is None:
            raise ValueError(
                f"Unsupported timeframe '{timeframe}'. "
                f"Supported: {list(GRANULARITY_MAP.keys())}"
            )
        return granularity

    @staticmethod
    def _parse_candles(candles: list[list]) -> pd.DataFrame:
        """Parse raw candle arrays into a DataFrame.

        Bitget v2 candle format:
        [timestamp_ms, open, high, low, close, volume_base, volume_quote]
        """
        records = []
        for c in candles:
            records.append(
                {
                    "timestamp": pd.Timestamp(int(c[0]), unit="ms", tz="UTC"),
                    "open": float(c[1]),
                    "high": float(c[2]),
                    "low": float(c[3]),
                    "close": float(c[4]),
                    "volume": float(c[5]),
                }
            )
        df = pd.DataFrame.from_records(records)
        df.set_index("timestamp", inplace=True)
        df.sort_index(inplace=True)
        return df

    @staticmethod
    def _empty_ohlcv() -> pd.DataFrame:
        """Return an empty DataFrame with the standard OHLCV schema."""
        df = pd.DataFrame(
            columns=["open", "high", "low", "close", "volume"]
        )
        df.index.name = "timestamp"
        return df
