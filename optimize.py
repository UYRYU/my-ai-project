"""
TP/SL パラメータの総当り最適化スクリプト。

評価軸:
  - total_r       : 累計 R
  - profit_factor : PF
  - sharpe        : R 列の Sharpe 近似 (mean / std)
  - expectancy    : 平均 R (= avg_r)

使い方:
  python3 optimize.py --synthetic                    # 合成データで最適化
  python3 optimize.py --csv data/xauusd_15m.csv      # CSV で最適化
  python3 optimize.py --synthetic --metric profit_factor --top 20
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd

from trading.backtest import run_backtest
from trading.data import load_csv, load_yfinance, synthetic_gold_15m


@dataclass
class ParamSet:
    sl_mode: str
    tp_mode: str
    rr_ratio: float
    swing_lookback: int
    atr_mult_sl: float
    atr_mult_tp: float

    def to_dict(self) -> dict:
        d = {
            "sl_mode": self.sl_mode,
            "tp_mode": self.tp_mode,
            "swing_lookback": self.swing_lookback,
        }
        if self.tp_mode == "rr":
            d["rr_ratio"] = self.rr_ratio
        if self.sl_mode == "atr":
            d["atr_mult_sl"] = self.atr_mult_sl
        if self.tp_mode == "atr":
            d["atr_mult_tp"] = self.atr_mult_tp
        return d


def build_grid() -> list[ParamSet]:
    """検証する全パラメータ組合せ。"""
    grid: list[ParamSet] = []

    swing_lookbacks = [10, 15, 20, 30, 50]
    rr_ratios = [0.5, 0.8, 1.0, 1.2, 1.5, 2.0, 2.5, 3.0]
    atr_mult_sl = [1.0, 1.5, 2.0, 2.5]
    atr_mult_tp = [1.0, 1.5, 2.0, 3.0, 4.0]

    # 1) swing SL × swing TP (lookback だけ振る)
    for sl in swing_lookbacks:
        grid.append(ParamSet("swing", "swing", 0.0, sl, 0.0, 0.0))

    # 2) swing SL × RR TP
    for sl in swing_lookbacks:
        for rr in rr_ratios:
            grid.append(ParamSet("swing", "rr", rr, sl, 0.0, 0.0))

    # 3) ATR SL × RR TP
    for sl_mult in atr_mult_sl:
        for rr in rr_ratios:
            grid.append(ParamSet("atr", "rr", rr, 20, sl_mult, 0.0))

    # 4) ATR SL × ATR TP
    for sl_mult in atr_mult_sl:
        for tp_mult in atr_mult_tp:
            if tp_mult <= sl_mult:
                continue
            grid.append(ParamSet("atr", "atr", 0.0, 20, sl_mult, tp_mult))

    return grid


def evaluate(df: pd.DataFrame, params: ParamSet) -> dict:
    trades, stats = run_backtest(
        df,
        ema_period=10,
        swing_lookback=params.swing_lookback,
        sl_mode=params.sl_mode,
        tp_mode=params.tp_mode,
        rr_ratio=params.rr_ratio,
        atr_mult_sl=params.atr_mult_sl,
        atr_mult_tp=params.atr_mult_tp,
    )
    if trades:
        rs = np.array([t.pnl_r for t in trades])
        sharpe = float(rs.mean() / rs.std()) if rs.std() > 0 else 0.0
    else:
        sharpe = 0.0
    stats["sharpe"] = sharpe
    return stats


def main() -> int:
    p = argparse.ArgumentParser(description="EMA10 strategy TP/SL optimizer")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv", help="CSV ファイルパス")
    src.add_argument("--yfinance", metavar="TICKER")
    src.add_argument("--synthetic", action="store_true")
    p.add_argument("--period", default="60d")
    p.add_argument("--interval", default="15m")
    p.add_argument(
        "--metric",
        default="total_r",
        choices=["total_r", "profit_factor", "sharpe", "avg_r", "win_rate"],
        help="ランキング基準 (default: total_r)",
    )
    p.add_argument("--min-trades", type=int, default=20, help="最低トレード数 (これ未満は除外)")
    p.add_argument("--top", type=int, default=10, help="表示する上位件数")
    p.add_argument("--out-json", help="全結果を JSON 保存")
    args = p.parse_args()

    if args.csv:
        df = load_csv(args.csv)
        label = f"CSV: {args.csv}"
    elif args.yfinance:
        df = load_yfinance(args.yfinance, period=args.period, interval=args.interval)
        label = f"yfinance: {args.yfinance}"
    else:
        df = synthetic_gold_15m()
        label = "synthetic gold 15m"

    print(f"=== Data: {label} ({len(df)} bars) ===")
    grid = build_grid()
    print(f"=== Sweeping {len(grid)} parameter combinations ===\n")

    results: list[tuple[ParamSet, dict]] = []
    for params in grid:
        stats = evaluate(df, params)
        results.append((params, stats))

    # フィルター: 最低トレード数
    filtered = [(p, s) for p, s in results if s["trades"] >= args.min_trades]
    if not filtered:
        print(f"No combinations met min-trades={args.min_trades}")
        return 1

    filtered.sort(key=lambda x: x[1].get(args.metric, 0.0), reverse=True)

    print(f"=== Top {args.top} by {args.metric} (min trades = {args.min_trades}) ===\n")
    header = (
        f"{'#':>3}  {'sl':>5}/{'tp':<5}  {'param':<14}  "
        f"{'trades':>6}  {'win%':>6}  {'avgR':>7}  {'totR':>7}  {'PF':>5}  {'DD':>6}  {'sharpe':>7}"
    )
    print(header)
    print("-" * len(header))
    for rank, (params, stats) in enumerate(filtered[: args.top], 1):
        if params.tp_mode == "rr":
            param_label = f"rr={params.rr_ratio} sw={params.swing_lookback}"
        elif params.tp_mode == "atr":
            param_label = f"atr_tp={params.atr_mult_tp}"
        else:
            param_label = f"sw={params.swing_lookback}"
        if params.sl_mode == "atr":
            param_label += f" atr_sl={params.atr_mult_sl}"
        print(
            f"{rank:>3}  {params.sl_mode:>5}/{params.tp_mode:<5}  {param_label:<14}  "
            f"{stats['trades']:>6}  {stats['win_rate']*100:>5.1f}%  "
            f"{stats['avg_r']:>+7.3f}  {stats['total_r']:>+7.2f}  "
            f"{stats['profit_factor']:>5.2f}  {stats['max_dd_r']:>6.2f}  "
            f"{stats['sharpe']:>+7.3f}"
        )

    if args.out_json:
        out = [{"params": p.to_dict(), "stats": s} for p, s in results]
        with open(args.out_json, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"\nfull results -> {args.out_json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
