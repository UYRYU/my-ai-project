"""ETH/DOGE/XRP/BTC で同じトレンドモード最適化を回し横並び比較.

run_trend_mode.py のロジックを多シンボル版に拡張.
ポジションサイジングは risk_pct でスケール不変にする.
"""
from __future__ import annotations

import itertools
import json
import math
from dataclasses import replace
from pathlib import Path

import pandas as pd

from optimize import score, write_set_file
from strategy import Params, backtest

REPO = Path(__file__).resolve().parent.parent

# (tag, csv) - 全て M15 maker
SYMBOLS = [
    ("BTCUSDT",  "data/btcusdt_15m_synth.csv"),
    ("ETHUSDT",  "data/ethusdt_15m_synth.csv"),
    ("DOGEUSDT", "data/dogeusdt_15m_synth.csv"),
    ("XRPUSDT",  "data/xrpusdt_15m_synth.csv"),
]

# トレンド向けフォーカスグリッド (run_trend_mode.py と同じ)
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


def run_grid(df: pd.DataFrame, base: Params, top_k: int = 5) -> list[dict]:
    rows = []
    for p in iter_params(base):
        m = backtest(df, p).metrics()
        m["score"] = round(score(m), 4)
        m["params"] = {k: getattr(p, k) for k in
                       list(TREND_GRID.keys()) + ["rsi_buy_min", "rsi_sell_max"]}
        rows.append(m)
    rows.sort(key=lambda x: x["score"], reverse=True)
    return rows[:top_k]


def walk_forward(df: pd.DataFrame, base: Params, n_folds: int = 3) -> list[dict]:
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
    return out


def main():
    rows = []
    for sym, csv in SYMBOLS:
        path = REPO / csv
        if not path.exists():
            print(f"[skip] {sym}: {csv} not found")
            continue
        df = pd.read_csv(path, parse_dates=["time"]).set_index("time")
        # risk_pct=0.5 でスケール不変サイジング (BTC でも DOGE でも同じ%リスク)
        base = Params(fee_rt_pct=0.04, slippage_pct=0.01,
                      risk_pct=0.5, fixed_qty=0.01)
        print(f"\n========== {sym} ==========", flush=True)
        print(f"  bars={len(df)}  range={df['close'].min():.6g}-{df['close'].max():.6g}",
              flush=True)

        is_top = run_grid(df, base, top_k=5)
        wf = walk_forward(df, base, n_folds=3)
        oos_pf = [x["pf"] for x in wf if math.isfinite(x["pf"])]
        oos_ret = [x["ret"] for x in wf]

        is_best = is_top[0]
        row = dict(
            symbol=sym,
            is_pf=is_best["pf"], is_ret=is_best["ret"], is_dd=is_best["max_dd"],
            is_n=is_best["n"], is_win=is_best["win"],
            oos_avg_pf=round(sum(oos_pf)/len(oos_pf), 3) if oos_pf else None,
            oos_avg_ret=round(sum(oos_ret)/len(oos_ret), 3) if oos_ret else None,
            oos_pfs=[round(x, 3) for x in oos_pf],
            best_params=is_best["params"],
        )
        print(f"  IS  pf={row['is_pf']} ret={row['is_ret']}% n={row['is_n']} win={row['is_win']}%")
        print(f"  OOS pfs={row['oos_pfs']} avg_pf={row['oos_avg_pf']} ret={row['oos_avg_ret']}%")
        print(f"  best params: ADX={is_best['params']['adx_min']} "
              f"EMA={is_best['params']['ema_fast']}/{is_best['params']['ema_slow']} "
              f"TP/SL={is_best['params']['tp_atr_mult']}/{is_best['params']['sl_atr_mult']}")

        out_dir = REPO / "results"
        suffix = sym.lower()
        (out_dir / f"top10_{suffix}_trend.json").write_text(
            json.dumps(is_top, indent=2, default=str))
        (out_dir / f"walkforward_{suffix}_trend.json").write_text(
            json.dumps(wf, indent=2, default=str))
        write_set_file(is_best["params"], out_dir / f"best_{suffix}_trend.set")
        rows.append(row)

    (REPO / "results" / "multi_symbol_matrix.json").write_text(
        json.dumps(rows, indent=2, default=str))

    print(f"\n{'symbol':10s}  IS_PF  IS_ret%  IS_n  OOS_PF  OOS_ret%  OOS_pfs")
    print("-" * 75)
    for r in rows:
        print(f"{r['symbol']:10s}  {r['is_pf']:5.2f}  {r['is_ret']:7.2f}  "
              f"{r['is_n']:4d}  {r['oos_avg_pf']:5.2f}  {r['oos_avg_ret']:8.2f}  "
              f"{r['oos_pfs']}")
    print(f"\nSaved -> results/multi_symbol_matrix.json")


if __name__ == "__main__":
    main()
