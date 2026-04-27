"""レジーム分割分析: バックテストを月単位 + 平均ADX強度で分けて成績を集計.

「ADXが立ちまくった月だけで稼いでないか」「レンジ月で破綻してないか」を見る.
トレンドフォロー戦略の挙動診断に役立つ.

Usage:
    python3 backtest/regime_split.py --csv data/btcusdt_15m_synth.csv \\
        --set results/best_btcusdt_trend.set
"""
from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from compare_fees import load_set, make_params
from strategy import adx, backtest

REPO = Path(__file__).resolve().parent.parent


def regime_classify(df: pd.DataFrame, adx_period: int = 14) -> pd.Series:
    """各月の平均 ADX で trend_strong / trend_weak / range を判定."""
    out = adx(df, adx_period)
    monthly_adx = out.resample("ME").mean()
    classification = pd.cut(
        monthly_adx,
        bins=[-np.inf, 18, 25, np.inf],
        labels=["range", "trend_weak", "trend_strong"],
    )
    return classification


def split_metrics_by_month(trades, equity: pd.Series) -> pd.DataFrame:
    """月別の取引集計."""
    if not trades:
        return pd.DataFrame()
    rows = [{
        "month": t.exit_time.to_period("M") if t.exit_time else None,
        "pnl": t.pnl,
        "win": 1 if t.pnl > 0 else 0,
    } for t in trades if t.exit_time is not None]
    df = pd.DataFrame(rows).dropna(subset=["month"])
    if df.empty:
        return pd.DataFrame()
    g = df.groupby("month").agg(
        n=("pnl", "size"),
        pnl_total=("pnl", "sum"),
        win=("win", "mean"),
        wins=("pnl", lambda s: float(s[s > 0].sum())),
        losses=("pnl", lambda s: float(-s[s < 0].sum())),
    )
    g["pf"] = g.apply(
        lambda r: (r["wins"] / r["losses"]) if r["losses"] > 0 else float("inf"),
        axis=1,
    )
    g["win"] = (g["win"] * 100).round(2)
    g = g.drop(columns=["wins", "losses"])
    return g


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--set", required=True)
    ap.add_argument("--fee", type=float, default=0.04)
    ap.add_argument("--slip", type=float, default=0.01)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    df = pd.read_csv(args.csv, parse_dates=["time"]).set_index("time")
    s = load_set(Path(args.set))
    base = make_params(s)
    base = replace(base, fee_rt_pct=args.fee, slippage_pct=args.slip)

    # 月別ADXレジーム
    regime = regime_classify(df, base.adx_period)
    regime_map = {idx.strftime("%Y-%m"): str(v)
                  for idx, v in regime.items()}

    # バックテスト実行
    res = backtest(df, base)
    monthly = split_metrics_by_month(res.trades, res.equity)
    monthly.index = monthly.index.astype(str)  # "YYYY-MM"
    monthly["regime"] = monthly.index.map(lambda m: regime_map.get(m, "unknown"))

    # レジーム別集計
    by_reg = monthly.groupby("regime").agg(
        months=("n", "size"),
        n=("n", "sum"),
        pnl_total=("pnl_total", "sum"),
        avg_pnl_per_month=("pnl_total", "mean"),
        avg_pf=("pf", lambda x: float(np.median(x[np.isfinite(x)])) if any(np.isfinite(x)) else float("nan")),
        avg_win=("win", "mean"),
    )

    print("\n=== Monthly breakdown ===")
    print(monthly.to_string())
    print("\n=== Regime aggregate ===")
    print(by_reg.to_string())

    out_path = Path(args.out or f"results/regime_split_{Path(args.set).stem}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(
        dict(monthly=monthly.reset_index().to_dict("records"),
             regime_aggregate=by_reg.reset_index().to_dict("records"),
             total=res.metrics()),
        indent=2, default=str,
    ))
    print(f"\nSaved -> {out_path}")


if __name__ == "__main__":
    main()
