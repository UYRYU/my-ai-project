"""
FX-Data/FX-Data-XAUUSD-DS (GitHub) からティックデータをダウンロードし、
15 分足 OHLC に集約して CSV 出力するスクリプト。

元リポジトリ: https://github.com/FX-Data/FX-Data-XAUUSD-DS
  - 2011〜2018 年の XAUUSD ティックデータをブランチごとに公開
  - 1 時間ごと 1 CSV (yyyy-mm-dd--HHh_ticks.csv)
  - 列: time, bid, ask, bid_volume, ask_volume
  - 価格は実際の 1/100 スケールで格納されているため 100 倍してから使用

使い方:
    python3 scripts/fetch_xauusd.py --year 2018 --months 01 02 03 \\
        --out data/xauusd_15m_2018q1.csv
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import sys
import time
import urllib.request
from pathlib import Path

import pandas as pd

API_BASE = "https://api.github.com/repos/FX-Data/FX-Data-XAUUSD-DS/contents/XAUUSD"
RAW_BASE = "https://raw.githubusercontent.com/FX-Data/FX-Data-XAUUSD-DS"


def list_files(year: str, month: str) -> list[str]:
    url = f"{API_BASE}/{year}/{month}?ref=XAUUSD-{year}"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    return [item["name"] for item in data if item["name"].endswith(".csv")]


def fetch_one(job: tuple[str, str, str, Path]) -> tuple[str, bool, int | str]:
    year, month, fname, cache_dir = job
    local = cache_dir / year / month / fname
    if local.exists() and local.stat().st_size > 0:
        return fname, True, 0
    local.parent.mkdir(parents=True, exist_ok=True)
    url = f"{RAW_BASE}/XAUUSD-{year}/XAUUSD/{year}/{month}/{fname}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            local.write_bytes(r.read())
        return fname, True, local.stat().st_size
    except Exception as e:
        return fname, False, str(e)


def download_months(year: str, months: list[str], cache_dir: Path, workers: int) -> list[Path]:
    all_jobs: list[tuple[str, str, str, Path]] = []
    for m in months:
        files = list_files(year, m)
        print(f"  {year}/{m}: {len(files)} files")
        all_jobs.extend((year, m, f, cache_dir) for f in files)

    print(f"\nDownloading {len(all_jobs)} files with {workers} workers...")
    t0 = time.time()
    done = 0
    errs = 0
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        for _, ok, _ in pool.map(fetch_one, all_jobs):
            done += 1
            if not ok:
                errs += 1
            if done % 200 == 0:
                print(f"  {done}/{len(all_jobs)}  ({time.time()-t0:.0f}s)")
    print(f"Done in {time.time()-t0:.0f}s  ({errs} errors)")

    paths = []
    for year, month, fname, _ in all_jobs:
        p = cache_dir / year / month / fname
        if p.exists():
            paths.append(p)
    return paths


def resample_to_15m(tick_files: list[Path]) -> pd.DataFrame:
    print(f"\nReading {len(tick_files)} tick files...")
    dfs = []
    for i, f in enumerate(tick_files):
        df = pd.read_csv(f, names=["time", "bid", "ask", "bv", "av"])
        dfs.append(df[["time", "bid", "ask"]])
        if (i + 1) % 300 == 0:
            print(f"  {i+1}/{len(tick_files)}")
    ticks = pd.concat(dfs, ignore_index=True)
    print(f"  total ticks: {len(ticks):,}")

    print("Parsing timestamps...")
    ticks["time"] = pd.to_datetime(ticks["time"], format="%Y.%m.%d %H:%M:%S.%f")
    ticks = ticks.sort_values("time").set_index("time")

    print("Resampling to 15m...")
    # 価格は 1/100 スケールなので 100 倍して実価格にする
    mid = (ticks["bid"] + ticks["ask"]) / 2 * 100
    ohlc = mid.resample("15min").agg(["first", "max", "min", "last"])
    ohlc.columns = ["open", "high", "low", "close"]
    return ohlc.dropna()


def main() -> int:
    p = argparse.ArgumentParser(description="Fetch XAUUSD ticks and resample to 15m")
    p.add_argument("--year", default="2018", help="対象年 (例: 2018)")
    p.add_argument("--months", nargs="+", default=["01", "02", "03"], help="対象月のリスト")
    p.add_argument("--out", required=True, help="出力 CSV パス")
    p.add_argument("--cache", default="data/xauusd_ticks", help="ティックキャッシュディレクトリ")
    p.add_argument("--workers", type=int, default=16)
    args = p.parse_args()

    cache_dir = Path(args.cache)
    cache_dir.mkdir(parents=True, exist_ok=True)

    print(f"=== Fetching XAUUSD {args.year} {args.months} ===")
    paths = download_months(args.year, args.months, cache_dir, args.workers)
    if not paths:
        print("No files downloaded")
        return 1

    ohlc = resample_to_15m(paths)
    print(f"\n15m bars: {len(ohlc)}")
    print(f"range: {ohlc.index[0]} -> {ohlc.index[-1]}")
    print(f"price range: {ohlc['low'].min():.2f} - {ohlc['high'].max():.2f}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    ohlc.to_csv(out)
    print(f"\nSaved: {out} ({out.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
