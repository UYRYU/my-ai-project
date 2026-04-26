"""best.set のパラメータで「Bitget手数料あり / なし」を比較し、
手数料がどれくらい性能を削っているかを可視化する補助スクリプト."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from strategy import Params, backtest


def load_set(path: Path) -> dict:
    out = {}
    for line in path.read_text().splitlines():
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if v.replace(".", "", 1).replace("-", "", 1).isdigit():
            out[k] = float(v) if "." in v else int(v)
        else:
            out[k] = v
    return out


def make_params(s: dict) -> Params:
    return Params(
        ema_fast=int(s["EMA_Fast"]), ema_slow=int(s["EMA_Slow"]),
        rsi_period=int(s["RSI_Period"]),
        rsi_buy_min=float(s["RSI_BuyMin"]), rsi_sell_max=float(s["RSI_SellMax"]),
        atr_period=int(s["ATR_Period"]), atr_min_mult=float(s["ATR_MinMult"]),
        tp_atr_mult=float(s["TP_ATR_Mult"]), sl_atr_mult=float(s["SL_ATR_Mult"]),
        trail_start_atr=float(s["TrailStart_ATR"]), trail_step_atr=float(s["TrailStep_ATR"]),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/btcusdt_5m_synth.csv")
    ap.add_argument("--set", default="results/best.set")
    args = ap.parse_args()

    df = pd.read_csv(args.csv, parse_dates=["time"]).set_index("time")
    s = load_set(Path(args.set))
    base = make_params(s)

    scenarios = [
        ("Bitget taker往復 0.12% + slip 0.02%",
         dict(fee_rt_pct=0.12, slippage_pct=0.02)),
        ("Bitget maker往復 0.04% + slip 0.01%",
         dict(fee_rt_pct=0.04, slippage_pct=0.01)),
        ("MT5想定 (スプレッド5pt相当 0.005%)",
         dict(fee_rt_pct=0.005, slippage_pct=0.005)),
        ("手数料ゼロ (理論上限)",
         dict(fee_rt_pct=0.0, slippage_pct=0.0)),
    ]
    print(f"\nParams: ema={base.ema_fast}/{base.ema_slow} "
          f"tp/sl={base.tp_atr_mult}/{base.sl_atr_mult} "
          f"atrMin={base.atr_min_mult} rsi={base.rsi_buy_min}/{base.rsi_sell_max}\n")
    print(f"{'scenario':50s}  n     PF      ret%     DD%    win%")
    print("-" * 90)
    rows = []
    for name, kw in scenarios:
        p = Params(**{**base.__dict__, **kw})
        m = backtest(df, p).metrics()
        print(f"{name:50s}  {m['n']:4d}  {m['pf']:5.2f}  {m['ret']:7.2f}  "
              f"{m['max_dd']:6.2f}  {m['win']:5.2f}")
        rows.append({"scenario": name, **kw, **m})
    Path("results/fee_sensitivity.json").write_text(
        json.dumps(rows, indent=2, default=str))
    print("\nSaved -> results/fee_sensitivity.json")


if __name__ == "__main__":
    main()
