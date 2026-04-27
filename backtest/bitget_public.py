"""Bitget v2 public API クライアント (スタンドアロン版).

claude/btc-trend-long-bot ブランチの実装を参考に, 依存を最小化:
  - loguru なし (標準 logging or print)
  - BaseExchange/ExchangeConfig なし (直接 base_url を持つ)
  - pandas + requests のみ

機能:
  - fetch_ohlcv_range: 期間指定で自動ページング (古い方向に1000本ずつ後ろ向き)
  - download_and_save: 既存CSV があれば差分のみ取得して追記
  - exponential backoff retry
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd
import requests


GRANULARITY_MAP: dict[str, str] = {
    "1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min",
    "1h": "1h",   "4h": "4h",   "1d": "1day",   "1w": "1week",
}
TIMEFRAME_MS: dict[str, int] = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000, "1w": 604_800_000,
}
MAX_CANDLES_PER_REQUEST = 1000
MAX_RETRIES = 3
RATE_LIMIT_DELAY = 0.1


@dataclass
class BitgetConfig:
    base_url: str = "https://api.bitget.com"
    product_type: str = "spot"   # "spot" or "usdt-futures"


class BitgetPublic:
    """Bitget v2 public REST market-data client."""

    def __init__(self, config: Optional[BitgetConfig] = None,
                 verbose: bool = True):
        self.cfg = config or BitgetConfig()
        self.verbose = verbose
        self._s = requests.Session()
        self._s.headers["Content-Type"] = "application/json"
        self._last_req = 0.0

    # -------------------------- public --------------------------

    def fetch_ohlcv_range(self, symbol: str, timeframe: str,
                          start_date: str, end_date: str) -> pd.DataFrame:
        """期間指定で OHLCV を取得 (古い方向にページング)."""
        granularity = self._granularity(timeframe)
        candle_ms = TIMEFRAME_MS[timeframe]
        start_ms = int(pd.Timestamp(start_date).timestamp() * 1000)
        end_ms = int(pd.Timestamp(end_date).timestamp() * 1000)

        frames: list[pd.DataFrame] = []
        cur_end = end_ms
        endpoint = self._candles_endpoint()

        while cur_end >= start_ms:
            params = dict(symbol=symbol, granularity=granularity,
                          endTime=str(cur_end),
                          limit=str(MAX_CANDLES_PER_REQUEST))
            if self.cfg.product_type != "spot":
                params["productType"] = self.cfg.product_type
            data = self._request(endpoint, params)
            candles = data.get("data") or []
            if not candles:
                break
            df = self._parse(candles)
            frames.append(df)
            oldest_ms = int(df.index.min().timestamp() * 1000)
            if oldest_ms <= start_ms:
                break
            cur_end = oldest_ms - candle_ms
            if len(candles) < MAX_CANDLES_PER_REQUEST:
                break

        if not frames:
            return self._empty()
        out = pd.concat(frames)
        out = out[~out.index.duplicated(keep="first")].sort_index()
        # 範囲フィルタ (tz-aware で揃える)
        s = pd.Timestamp(start_date, tz="UTC")
        e = pd.Timestamp(end_date, tz="UTC")
        out = out.loc[(out.index >= s) & (out.index <= e)]
        if self.verbose:
            print(f"  [bitget] {symbol} {timeframe}  fetched {len(out)} bars  "
                  f"({out.index.min()} -> {out.index.max()})")
        return out

    def download_and_save(self, symbol: str, timeframe: str,
                          start_date: str, end_date: str,
                          out_path: Path) -> Path:
        """CSV へ保存. 既存ファイルがあれば差分のみ追記."""
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        effective_start = start_date
        if out_path.exists():
            existing = pd.read_csv(out_path, index_col=0, parse_dates=True)
            if not existing.empty:
                last_ts = existing.index.max()
                cm = TIMEFRAME_MS[timeframe]
                new_start = int(last_ts.timestamp() * 1000) + cm
                effective_start = str(pd.Timestamp(new_start, unit="ms", tz="UTC"))
                if pd.Timestamp(effective_start, tz="UTC") > pd.Timestamp(end_date, tz="UTC"):
                    if self.verbose:
                        print(f"  [bitget] {symbol} already up to date.")
                    return out_path
                new = self.fetch_ohlcv_range(symbol, timeframe, effective_start, end_date)
                if new.empty:
                    return out_path
                merged = pd.concat([existing, new])
                merged = merged[~merged.index.duplicated(keep="last")].sort_index()
                merged.to_csv(out_path, index_label="time")
                if self.verbose:
                    print(f"  [bitget] {symbol} appended {len(new)}, total {len(merged)} -> {out_path}")
                return out_path

        df = self.fetch_ohlcv_range(symbol, timeframe, start_date, end_date)
        if not df.empty:
            df.to_csv(out_path, index_label="time")
            if self.verbose:
                print(f"  [bitget] saved {len(df)} -> {out_path}")
        return out_path

    # -------------------------- internal --------------------------

    def _candles_endpoint(self) -> str:
        if self.cfg.product_type == "spot":
            return "/api/v2/spot/market/candles"
        return "/api/v2/mix/market/history-candles"

    def _request(self, endpoint: str, params: dict) -> dict:
        url = self.cfg.base_url.rstrip("/") + endpoint
        for attempt in range(1, MAX_RETRIES + 1):
            elapsed = time.monotonic() - self._last_req
            if elapsed < RATE_LIMIT_DELAY:
                time.sleep(RATE_LIMIT_DELAY - elapsed)
            try:
                self._last_req = time.monotonic()
                r = self._s.get(url, params=params, timeout=30)
                r.raise_for_status()
                body = r.json()
                code = str(body.get("code", ""))
                if code not in ("00000", "0"):
                    raise RuntimeError(f"Bitget API code={code}: {body.get('msg')}")
                return body
            except (requests.RequestException, RuntimeError) as e:
                backoff = 2 ** (attempt - 1)
                if attempt < MAX_RETRIES:
                    if self.verbose:
                        print(f"  [bitget] retry {attempt}/{MAX_RETRIES} in {backoff}s: {e}")
                    time.sleep(backoff)
                else:
                    raise

    @staticmethod
    def _granularity(tf: str) -> str:
        g = GRANULARITY_MAP.get(tf)
        if g is None:
            raise ValueError(f"Unsupported timeframe {tf}. "
                             f"Supported: {list(GRANULARITY_MAP)}")
        return g

    @staticmethod
    def _parse(candles: list) -> pd.DataFrame:
        recs = [
            dict(
                timestamp=pd.Timestamp(int(c[0]), unit="ms", tz="UTC"),
                open=float(c[1]), high=float(c[2]), low=float(c[3]),
                close=float(c[4]), volume=float(c[5]),
            )
            for c in candles
        ]
        df = pd.DataFrame.from_records(recs).set_index("timestamp")
        return df.sort_index()

    @staticmethod
    def _empty() -> pd.DataFrame:
        df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        df.index.name = "timestamp"
        return df


# CLI
def _main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--tf", default="15m", choices=list(GRANULARITY_MAP))
    ap.add_argument("--start", required=True, help="ISO date e.g. 2024-01-01")
    ap.add_argument("--end", default=None,
                    help="ISO date (default: now)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--product", default="spot",
                    choices=["spot", "usdt-futures"])
    args = ap.parse_args()
    end = args.end or pd.Timestamp.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    out = Path(args.out or f"data/{args.symbol.lower()}_{args.tf}.csv")
    cli = BitgetPublic(BitgetConfig(product_type=args.product))
    cli.download_and_save(args.symbol, args.tf, args.start, end, out)


if __name__ == "__main__":
    _main()
