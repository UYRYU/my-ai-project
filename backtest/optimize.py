"""Grid + Walk-Forward 最適化."""
from __future__ import annotations

import argparse
import itertools
import json
import math
from dataclasses import asdict, replace
from pathlib import Path

import pandas as pd

from strategy import Params, backtest


# ---- 探索グリッド (重すぎない範囲) ----
GRID = dict(
    ema_fast      = [9, 20, 34],
    ema_slow      = [50, 100, 200],
    rsi_buy_min   = [45.0, 55.0],
    rsi_sell_max  = [45.0, 55.0],
    atr_min_mult  = [0.8, 1.2],
    tp_atr_mult   = [3.0, 6.0, 10.0],   # Bitget手数料に負けないため大きめ
    sl_atr_mult   = [1.0, 1.5, 2.0],
    trail_start_atr = [1.0, 2.0],
    trail_step_atr  = [0.5, 1.0],
)


def iter_params(base: Params):
    keys = list(GRID.keys())
    for combo in itertools.product(*[GRID[k] for k in keys]):
        kw = dict(zip(keys, combo))
        # 早期足切り：ema_fast >= ema_slow / RSI buy<sell
        if kw["ema_fast"] >= kw["ema_slow"]:
            continue
        if kw["rsi_buy_min"] > kw["rsi_sell_max"] + 10:  # 極端な反転を除外
            continue
        yield replace(base, **kw)


MIN_TRADES = 20  # WFA の OOS が短くても弾かないように低め

def score(m: dict) -> float:
    """PF と DD と 取引数の合成スコア."""
    if m["n"] < MIN_TRADES:
        return -1.0
    pf = m["pf"] if math.isfinite(m["pf"]) else 0.0
    dd_pen = abs(m["max_dd"]) / 100.0
    return pf * (1.0 - min(dd_pen, 0.9)) * (1.0 + min(m["ret"], 200.0) / 200.0)


def run_grid(df: pd.DataFrame, base: Params, top_k: int = 10) -> list[dict]:
    rows = []
    total = sum(1 for _ in iter_params(base))
    print(f"Grid size: {total}")
    i = 0
    for p in iter_params(base):
        i += 1
        res = backtest(df, p)
        m = res.metrics()
        m["score"] = round(score(m), 4)
        m["params"] = {k: getattr(p, k) for k in GRID.keys()}
        rows.append(m)
        if i % 50 == 0 or i == total:
            print(f"  [{i}/{total}] best so far: "
                  f"{max(rows, key=lambda x: x['score'])['score']:.3f}")
    rows.sort(key=lambda x: x["score"], reverse=True)
    return rows[:top_k]


def walk_forward(df: pd.DataFrame, base: Params, n_folds: int = 4) -> list[dict]:
    """In-Sample で最適化 → Out-of-Sample で検証 を n_folds 回."""
    n = len(df)
    fold = n // (n_folds + 1)
    oos_results = []
    for k in range(n_folds):
        is_end  = fold * (k + 1)
        oos_end = fold * (k + 2)
        is_df   = df.iloc[:is_end]
        oos_df  = df.iloc[is_end:oos_end]
        if len(is_df) < 500 or len(oos_df) < 200:
            continue
        print(f"\n== Fold {k+1}/{n_folds} ==")
        print(f"  IS  : {is_df.index[0]} -> {is_df.index[-1]} ({len(is_df)})")
        print(f"  OOS : {oos_df.index[0]} -> {oos_df.index[-1]} ({len(oos_df)})")
        top = run_grid(is_df, base, top_k=1)
        if not top:
            continue
        best = top[0]
        p_best = replace(base, **best["params"])
        oos = backtest(oos_df, p_best).metrics()
        oos["score"] = round(score(oos), 4)
        oos["params"] = best["params"]
        oos["fold"] = k + 1
        oos["is_score"] = best["score"]
        oos_results.append(oos)
        print(f"  IS  best score={best['score']:.3f}  pf={best['pf']}  dd={best['max_dd']}")
        print(f"  OOS       score={oos['score']:.3f}  pf={oos['pf']}  dd={oos['max_dd']}  n={oos['n']}")
    return oos_results


def write_set_file(params: dict, out_path: Path):
    """MT5 .set 形式 (input名=値) で書き出し."""
    mapping = dict(
        EMA_Fast=params["ema_fast"],
        EMA_Slow=params["ema_slow"],
        RSI_Period=14,
        RSI_BuyMin=params["rsi_buy_min"],
        RSI_SellMax=params["rsi_sell_max"],
        ATR_Period=14,
        ATR_MinMult=params["atr_min_mult"],
        TP_ATR_Mult=params["tp_atr_mult"],
        SL_ATR_Mult=params["sl_atr_mult"],
        TrailStart_ATR=params["trail_start_atr"],
        TrailStep_ATR=params["trail_step_atr"],
        CloseOnSignal="true",
        RiskPercent=0.0,           # Pythonバックテストと揃える: 固定ロット
        FixedLot=0.01,
        MaxConsecLoss=3,
        CooldownMinutes=300,       # M5×60本 = 300分
        MagicNumber=20260426,
        SlippagePoints=30,
        FeePercentRT=0.12,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        for k, v in mapping.items():
            f.write(f"{k}={v}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/btcusdt_5m.csv")
    ap.add_argument("--out", default="results")
    ap.add_argument("--folds", type=int, default=4)
    ap.add_argument("--fee", type=float, default=0.12,
                    help="Round-trip fee in pct (Bitget taker=0.12, maker=0.04)")
    ap.add_argument("--slip", type=float, default=0.02,
                    help="One-way slippage pct")
    ap.add_argument("--tag", default="",
                    help="Suffix for output filenames (e.g. h1_maker)")
    ap.add_argument("--quick", action="store_true",
                    help="グリッドを縮小して素早く回す")
    args = ap.parse_args()

    if args.quick:
        # 動作確認用に縮小
        for k, v in list(GRID.items()):
            GRID[k] = v[:2]

    df = pd.read_csv(args.csv, parse_dates=["time"]).set_index("time")
    print(f"Loaded {len(df)} bars: {df.index[0]} -> {df.index[-1]}")
    print(f"Fee/slip: RT={args.fee}% slip={args.slip}%")

    base = Params(fee_rt_pct=args.fee, slippage_pct=args.slip)

    print("\n### 1) Full-period grid search ###")
    top = run_grid(df, base, top_k=10)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = f"_{args.tag}" if args.tag else ""
    top_path = out_dir / f"top10{suffix}.json"
    set_path = out_dir / f"best{suffix}.set"
    wf_path  = out_dir / f"walkforward{suffix}.json"

    with top_path.open("w") as f:
        json.dump(top, f, indent=2, default=str)
    print(f"\nTop 10 saved -> {top_path}")
    for i, r in enumerate(top[:5], 1):
        print(f"  #{i} score={r['score']}  pf={r['pf']}  ret={r['ret']}%  "
              f"dd={r['max_dd']}%  n={r['n']}  win={r['win']}%")
        print(f"      params={r['params']}")

    write_set_file(top[0]["params"], set_path)
    print(f".set saved -> {set_path}")

    print("\n### 2) Walk-Forward Analysis ###")
    wf = walk_forward(df, base, n_folds=args.folds)
    with wf_path.open("w") as f:
        json.dump(wf, f, indent=2, default=str)
    if wf:
        oos_pf = [x["pf"] for x in wf if math.isfinite(x["pf"])]
        oos_ret = [x["ret"] for x in wf]
        print(f"\nOOS summary: avg PF={sum(oos_pf)/len(oos_pf):.2f}  "
              f"avg ret={sum(oos_ret)/len(oos_ret):.2f}%  folds={len(wf)}")


if __name__ == "__main__":
    main()
