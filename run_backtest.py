"""
EMA10 × 15分足 × ローソク足パターン バックテスト実行スクリプト。

使い方:
    # オフライン (ダミーデータ)
    python run_backtest.py --synthetic

    # yfinance で GC=F (COMEX 金先物) を取得してバックテスト
    python run_backtest.py --yfinance GC=F --period 60d

    # 自前 CSV (index=timestamp, columns=open,high,low,close)
    python run_backtest.py --csv data/xauusd_15m.csv
"""

from __future__ import annotations

import argparse
import json
import sys

from trading.backtest import run_backtest
from trading.data import load_csv, load_yfinance, synthetic_gold_15m


def main() -> int:
    p = argparse.ArgumentParser(description="EMA10 x 15m backtester")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv", help="CSV ファイルパス")
    src.add_argument("--yfinance", metavar="TICKER", help="yfinance ティッカー (例: GC=F)")
    src.add_argument("--synthetic", action="store_true", help="ダミーデータで実行")

    p.add_argument("--period", default="60d", help="yfinance 期間 (default: 60d)")
    p.add_argument("--interval", default="15m", help="yfinance 間隔 (default: 15m)")
    p.add_argument("--ema", type=int, default=10, help="EMA 期間 (default: 10)")
    p.add_argument("--swing", type=int, default=20, help="直近高値/安値の参照本数 (default: 20)")
    p.add_argument("--max-bars", type=int, default=500, help="1 トレードの最大保有本数")
    p.add_argument("--trades-json", help="トレード明細を JSON 保存するパス")
    args = p.parse_args()

    if args.csv:
        df = load_csv(args.csv)
        label = f"CSV: {args.csv}"
    elif args.yfinance:
        df = load_yfinance(args.yfinance, period=args.period, interval=args.interval)
        label = f"yfinance: {args.yfinance} ({args.period}/{args.interval})"
    else:
        df = synthetic_gold_15m()
        label = "synthetic gold 15m"

    print(f"=== Data: {label} ===")
    print(f"bars: {len(df)}  range: {df.index[0]} → {df.index[-1]}")

    trades, stats = run_backtest(
        df,
        ema_period=args.ema,
        swing_lookback=args.swing,
        max_bars_per_trade=args.max_bars,
    )

    print()
    print("=== Stats ===")
    for k, v in stats.items():
        if isinstance(v, float):
            print(f"  {k:>14}: {v:.4f}")
        else:
            print(f"  {k:>14}: {v}")

    if args.trades_json:
        with open(args.trades_json, "w", encoding="utf-8") as f:
            json.dump([t.to_dict() for t in trades], f, ensure_ascii=False, indent=2)
        print(f"\ntrades saved to {args.trades_json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
