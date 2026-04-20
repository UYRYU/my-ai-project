"""Read-only Polymarket API wrapper (Gamma + Data + CLOB).

By design this module has NO trading surface. It only fetches:

- Gamma: market and event metadata (search, list, close times, outcomes).
- Data API: price and trade history for historical backtests.
- CLOB: best bid/ask mid for live scanning (GET only).

If you need to place orders, use a separate module outside this package.
This boundary is enforced by convention and by the absence of any
signing or private-key handling here.

Responses are cached on disk as JSON/parquet so repeat runs are offline.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class PolymarketClient:
    cache_dir: Path
    gamma_url: str = "https://gamma-api.polymarket.com"
    data_url: str = "https://data-api.polymarket.com"
    clob_url: str = "https://clob.polymarket.com"
    timeout_s: float = 20.0
    max_retries: int = 4
    # Session-level in-memory cache to cut redundant disk reads per run.
    _memo: dict[str, Any] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self.cache_dir = Path(self.cache_dir)
        (self.cache_dir / "polymarket").mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- Gamma
    def list_markets(
        self,
        *,
        tag: str | None = None,
        limit: int = 500,
        active: bool | None = None,
        closed: bool | None = None,
        use_cache: bool = True,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if tag is not None:
            params["tag"] = tag
        if active is not None:
            params["active"] = str(active).lower()
        if closed is not None:
            params["closed"] = str(closed).lower()
        url = f"{self.gamma_url}/markets?{urllib.parse.urlencode(params)}"
        data = self._get_json(url, use_cache=use_cache)
        return data if isinstance(data, list) else data.get("data", [])

    def search_events(
        self, query: str, limit: int = 100, use_cache: bool = True
    ) -> list[dict[str, Any]]:
        params = {"q": query, "limit": limit}
        url = f"{self.gamma_url}/events?{urllib.parse.urlencode(params)}"
        data = self._get_json(url, use_cache=use_cache)
        return data if isinstance(data, list) else data.get("data", [])

    def get_market(self, condition_id: str, use_cache: bool = True) -> dict[str, Any]:
        url = f"{self.gamma_url}/markets/{urllib.parse.quote(condition_id, safe='')}"
        return self._get_json(url, use_cache=use_cache)

    # ---------------------------------------------------------------- Data
    def price_history(
        self,
        token_id: str,
        *,
        start_ts: int | None = None,
        end_ts: int | None = None,
        interval: str = "1m",
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """Return a DataFrame of (timestamp_utc, price) for a CLOB token.

        Polymarket Data API exposes ``/prices-history`` which returns
        minute-level prices for a token. The schema has shifted over time;
        we defensively flatten whatever comes back.
        """
        params: dict[str, Any] = {"market": token_id, "interval": interval}
        if start_ts is not None:
            params["startTs"] = start_ts
        if end_ts is not None:
            params["endTs"] = end_ts
        url = f"{self.data_url}/prices-history?{urllib.parse.urlencode(params)}"
        raw = self._get_json(url, use_cache=use_cache)
        rows = raw.get("history") if isinstance(raw, dict) else raw
        if not rows:
            return pd.DataFrame(columns=["price"], index=pd.DatetimeIndex([], tz="UTC"))
        df = pd.DataFrame(rows)
        # Common column names across API versions.
        ts_col = _first_present(df, ["t", "timestamp", "ts"])
        px_col = _first_present(df, ["p", "price", "mid"])
        df = df[[ts_col, px_col]].rename(columns={ts_col: "timestamp", px_col: "price"})
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
        return df.set_index("timestamp").sort_index()

    # ---------------------------------------------------------------- CLOB
    def clob_book(self, token_id: str, use_cache: bool = False) -> dict[str, Any]:
        """Return current orderbook. Defaults to NO cache for live use."""
        url = f"{self.clob_url}/book?token_id={urllib.parse.quote(token_id, safe='')}"
        return self._get_json(url, use_cache=use_cache)

    def clob_mid(self, token_id: str) -> float | None:
        book = self.clob_book(token_id, use_cache=False)
        bids = book.get("bids") or []
        asks = book.get("asks") or []
        if not bids or not asks:
            return None
        best_bid = float(bids[0]["price"])
        best_ask = float(asks[0]["price"])
        return 0.5 * (best_bid + best_ask)

    # ---------------------------------------------------------------- plumbing
    def _get_json(self, url: str, use_cache: bool) -> Any:
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()
        if use_cache and key in self._memo:
            return self._memo[key]
        cache_file = self.cache_dir / "polymarket" / f"{key}.json"
        if use_cache and cache_file.exists():
            raw = cache_file.read_text(encoding="utf-8")
            data = json.loads(raw)
            self._memo[key] = data
            return data
        data = self._http_get_json(url)
        if use_cache:
            cache_file.write_text(json.dumps(data), encoding="utf-8")
        self._memo[key] = data
        return data

    def _http_get_json(self, url: str) -> Any:
        for attempt in range(self.max_retries):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "bs-edge/0.1"})
                with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                    return json.loads(resp.read())
            except Exception as exc:
                backoff = 2 ** attempt
                logger.warning("polymarket GET failed (%s); retry in %ds", exc, backoff)
                time.sleep(backoff)
        raise RuntimeError(f"polymarket GET exhausted retries: {url}")


def _first_present(df: pd.DataFrame, candidates: list[str]) -> str:
    for c in candidates:
        if c in df.columns:
            return c
    raise KeyError(f"none of {candidates} found in columns {list(df.columns)}")
