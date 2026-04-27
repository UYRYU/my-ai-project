"""パラメータ感度テスト: 最良パラメータ周辺で 1 軸ずつ振って性能変化を測る.

ロバストな最適解は ± 周辺でも性能が滑らかに維持される (= プラトー).
鋭利なピークだけの解は実機で過剰最適化的にコケやすい.

Usage:
    python3 backtest/sensitivity.py --csv data/btcusdt_15m_synth.csv \\
        --set results/best_btcusdt_trend.set
"""
from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

import pandas as pd

from compare_fees import load_set, make_params  # 既存の .set ローダー流用
from strategy import Params, backtest


REPO = Path(__file__).resolve().parent.parent

# 各次元を ±N% / ±N で振る (中央値=現状値)
SENSITIVITY: dict[str, list] = {
    "ema_fast":        [-30, -15, 0, 15, 30],   # %
    "ema_slow":        [-30, -15, 0, 15, 30],   # %
    "atr_min_mult":    [-0.4, -0.2, 0.0, 0.2, 0.4],   # 絶対
    "tp_atr_mult":     [-2.0, -1.0, 0.0, 1.0, 2.0],   # 絶対
    "sl_atr_mult":     [-0.5, -0.25, 0.0, 0.25, 0.5], # 絶対
    "trail_start_atr": [-0.5, -0.25, 0.0, 0.25, 0.5], # 絶対
    "adx_min":         [-10, -5, 0, 5, 10],     # 絶対
}


def perturb(p: Params, dim: str, delta: float) -> Params:
    cur = getattr(p, dim)
    if dim in ("ema_fast", "ema_slow"):
        new = max(2, int(round(cur * (1 + delta / 100))))
    else:
        new = max(0.0, cur + delta)
    return replace(p, **{dim: new})


def run_sensitivity(df: pd.DataFrame, base: Params) -> dict:
    """各次元を1つずつ振って PF/ret を測る."""
    results: dict[str, list] = {}
    base_metric = backtest(df, base).metrics()
    for dim, deltas in SENSITIVITY.items():
        rows = []
        for d in deltas:
            if d == 0 or (dim in ("ema_fast", "ema_slow") and d == 0):
                m = base_metric
                cur_val = getattr(base, dim)
            else:
                p2 = perturb(base, dim, d)
                m = backtest(df, p2).metrics()
                cur_val = getattr(p2, dim)
            rows.append({
                "delta": d, "value": cur_val,
                "pf": m["pf"], "ret": m["ret"],
                "n": m["n"], "win": m["win"], "dd": m["max_dd"],
            })
        results[dim] = rows
    return dict(base=base_metric, base_params={k: getattr(base, k) for k in SENSITIVITY},
                axes=results)


def print_table(out: dict, label: str):
    print(f"\n=== Sensitivity around best ({label}) ===")
    print(f"  Base   : PF={out['base']['pf']:.2f}  ret={out['base']['ret']:.2f}%  "
          f"n={out['base']['n']}  win={out['base']['win']:.1f}%")
    for dim, rows in out["axes"].items():
        cur = out["base_params"][dim]
        print(f"\n  {dim} (current={cur}):")
        print(f"    {'Δ':>8s}  {'value':>8s}  {'PF':>6s}  {'ret%':>8s}  {'n':>5s}")
        for r in rows:
            d_fmt = f"{r['delta']:+.2f}" if isinstance(r['delta'], float) else f"{r['delta']:+d}"
            v_fmt = f"{r['value']:.2f}" if isinstance(r['value'], float) else f"{r['value']}"
            print(f"    {d_fmt:>8s}  {v_fmt:>8s}  {r['pf']:>6.2f}  "
                  f"{r['ret']:>8.2f}  {r['n']:>5d}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--set", required=True, help=".set file with best params")
    ap.add_argument("--fee", type=float, default=0.04)
    ap.add_argument("--slip", type=float, default=0.01)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    df = pd.read_csv(args.csv, parse_dates=["time"]).set_index("time")
    s = load_set(Path(args.set))
    base = make_params(s)
    base = replace(base, fee_rt_pct=args.fee, slippage_pct=args.slip)

    label = Path(args.set).stem
    out = run_sensitivity(df, base)
    print_table(out, label)

    out_path = Path(args.out or f"results/sensitivity_{label}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nSaved -> {out_path}")


if __name__ == "__main__":
    main()
