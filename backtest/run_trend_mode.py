"""トレンドフォロー強化版 (ADX + HTF + trail-only) を M15 maker で最適化.

baseline (results/best_m15_maker.set) と直接比較する.
"""
from __future__ import annotations

import itertools
import json
import math
from dataclasses import replace
from pathlib import Path

import pandas as pd

from optimize import score, walk_forward, write_set_file
from strategy import Params, backtest

REPO = Path(__file__).resolve().parent.parent

# トレンド向けフォーカスグリッド (RSI 非対称は固定)
TREND_GRID = dict(
    ema_fast        = [20, 34],
    ema_slow        = [100, 200],
    atr_min_mult    = [0.8, 1.2],
    tp_atr_mult     = [6.0, 10.0],
    sl_atr_mult     = [1.0, 1.5],
    trail_start_atr = [1.0, 2.0],
    trail_step_atr  = [0.5, 1.0],
    adx_min         = [0.0, 20.0, 25.0, 30.0],
    htf_ratio       = [0, 4],
    trail_only      = [False, True],
)


def iter_params(base: Params):
    keys = list(TREND_GRID.keys())
    for combo in itertools.product(*[TREND_GRID[k] for k in keys]):
        kw = dict(zip(keys, combo))
        if kw["ema_fast"] >= kw["ema_slow"]:
            continue
        yield replace(base, rsi_buy_min=55.0, rsi_sell_max=45.0, **kw)


def run_grid(df: pd.DataFrame, base: Params, top_k: int = 10) -> list[dict]:
    rows = []
    total = sum(1 for _ in iter_params(base))
    print(f"Grid size: {total}", flush=True)
    i = 0
    for p in iter_params(base):
        i += 1
        m = backtest(df, p).metrics()
        m["score"] = round(score(m), 4)
        # store all dims that vary
        m["params"] = {k: getattr(p, k) for k in
                       list(TREND_GRID.keys()) + ["rsi_buy_min", "rsi_sell_max"]}
        rows.append(m)
        if i % 100 == 0 or i == total:
            print(f"  [{i}/{total}] best so far: "
                  f"{max(rows, key=lambda x: x['score'])['score']:.3f}", flush=True)
    rows.sort(key=lambda x: x["score"], reverse=True)
    return rows[:top_k]


def walk_forward_local(df: pd.DataFrame, base: Params, n_folds: int = 3) -> list[dict]:
    n = len(df)
    fold = n // (n_folds + 1)
    out = []
    for k in range(n_folds):
        is_end = fold * (k + 1)
        oos_end = fold * (k + 2)
        is_df = df.iloc[:is_end]
        oos_df = df.iloc[is_end:oos_end]
        if len(is_df) < 500 or len(oos_df) < 200:
            continue
        print(f"\n== Fold {k+1}/{n_folds} ==", flush=True)
        print(f"  IS  : {is_df.index[0]} -> {is_df.index[-1]} ({len(is_df)})")
        print(f"  OOS : {oos_df.index[0]} -> {oos_df.index[-1]} ({len(oos_df)})")
        top = run_grid(is_df, base, top_k=1)
        if not top:
            continue
        best = top[0]
        rsi_kw = {k: best["params"][k] for k in ("rsi_buy_min", "rsi_sell_max")}
        grid_kw = {k: best["params"][k] for k in TREND_GRID.keys()}
        p_best = replace(base, **rsi_kw, **grid_kw)
        oos = backtest(oos_df, p_best).metrics()
        oos["score"] = round(score(oos), 4)
        oos["params"] = best["params"]
        oos["fold"] = k + 1
        oos["is_score"] = best["score"]
        out.append(oos)
        print(f"  IS  best score={best['score']:.3f} pf={best['pf']} dd={best['max_dd']}")
        print(f"  OOS       score={oos['score']:.3f} pf={oos['pf']} dd={oos['max_dd']} n={oos['n']}")
    return out


def main():
    csv = REPO / "data/btcusdt_15m_synth.csv"
    df = pd.read_csv(csv, parse_dates=["time"]).set_index("time")
    print(f"Loaded {len(df)} bars: {df.index[0]} -> {df.index[-1]}")
    base = Params(fee_rt_pct=0.04, slippage_pct=0.01)

    print("\n### 1) Trend-mode full grid ###")
    top = run_grid(df, base, top_k=10)
    out_dir = REPO / "results"
    (out_dir / "top10_m15_maker_trend.json").write_text(
        json.dumps(top, indent=2, default=str))
    print(f"\nTop 5:")
    for i, r in enumerate(top[:5], 1):
        print(f"  #{i} score={r['score']} pf={r['pf']} ret={r['ret']}% "
              f"dd={r['max_dd']}% n={r['n']} win={r['win']}%")
        print(f"      adx={r['params']['adx_min']} htf={r['params']['htf_ratio']} "
              f"trail_only={r['params']['trail_only']} "
              f"ema={r['params']['ema_fast']}/{r['params']['ema_slow']} "
              f"tp/sl={r['params']['tp_atr_mult']}/{r['params']['sl_atr_mult']}")

    write_set_file(top[0]["params"], out_dir / "best_m15_maker_trend.set")

    print("\n### 2) Walk-Forward ###")
    wf = walk_forward_local(df, base, n_folds=3)
    (out_dir / "walkforward_m15_maker_trend.json").write_text(
        json.dumps(wf, indent=2, default=str))
    if wf:
        oos_pf = [x["pf"] for x in wf if math.isfinite(x["pf"])]
        oos_ret = [x["ret"] for x in wf]
        print(f"\nOOS summary: avg PF={sum(oos_pf)/len(oos_pf):.3f}  "
              f"avg ret={sum(oos_ret)/len(oos_ret):.3f}%")

    # baseline と並べる
    baseline = json.loads((out_dir / "walkforward_m15_maker.json").read_text())
    base_oos_pf = [x["pf"] for x in baseline if math.isfinite(x["pf"])]
    print(f"\n=== Comparison ===")
    print(f"baseline M15+maker      OOS avg PF = {sum(base_oos_pf)/len(base_oos_pf):.3f}")
    if wf:
        print(f"trend-mode M15+maker    OOS avg PF = {sum(oos_pf)/len(oos_pf):.3f}")


if __name__ == "__main__":
    main()
