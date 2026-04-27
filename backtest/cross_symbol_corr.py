"""シンボル間のシグナル発生相関 + ポートフォリオ効果分析.

各シンボルの buy/sell シグナルを同じ TF でアラインして:
  1. 同時発火の確率 (相関行列)
  2. ポジション保有時間の重複度
  3. 等重みポートフォリオの DD / Sharpe (単一シンボル比)

を測定. 相関低 = 分散効果あり = 合計リスク下がる.

Usage:
    python3 backtest/cross_symbol_corr.py
"""
from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from compare_fees import load_set, make_params
from strategy import backtest, prepare


REPO = Path(__file__).resolve().parent.parent

SYMBOLS = [
    ("BTCUSDT",  "data/btcusdt_15m_synth.csv",  "results/best_btcusdt_trend.set"),
    ("ETHUSDT",  "data/ethusdt_15m_synth.csv",  "results/best_ethusdt_trend.set"),
    ("DOGEUSDT", "data/dogeusdt_15m_synth.csv", "results/best_dogeusdt_trend.set"),
    ("XRPUSDT",  "data/xrpusdt_15m_synth.csv",  "results/best_xrpusdt_trend.set"),
]


def signal_series(df: pd.DataFrame, p) -> pd.DataFrame:
    """各バーで buy/sell シグナルが立った/立っていないの 0/1 系列."""
    d = prepare(df, p)
    d["atr_avg20"] = d["atr"].rolling(20, min_periods=5).mean()
    vol_ok = d["atr"] >= d["atr_avg20"] * p.atr_min_mult
    if p.adx_min > 0:
        adx_ok = d["adx"] >= p.adx_min
    else:
        adx_ok = pd.Series(True, index=d.index)
    if p.htf_ratio > 1:
        htf_long_ok = d["htf_dir"] >= 0
        htf_short_ok = d["htf_dir"] <= 0
    else:
        htf_long_ok = pd.Series(True, index=d.index)
        htf_short_ok = pd.Series(True, index=d.index)
    buy = ((d["ema_f"] > d["ema_s"]) & (d["rsi"] >= p.rsi_buy_min)
           & vol_ok & adx_ok & htf_long_ok)
    sell = ((d["ema_f"] < d["ema_s"]) & (d["rsi"] <= p.rsi_sell_max)
            & vol_ok & adx_ok & htf_short_ok)
    return pd.DataFrame({"buy": buy.astype(int), "sell": sell.astype(int),
                         "any": (buy | sell).astype(int)})


def position_series(df: pd.DataFrame, p) -> pd.Series:
    """各バーでポジ保有中なら 1, それ以外 0 (バックテスト結果から再構築)."""
    res = backtest(df, p)
    held = pd.Series(0, index=df.index, dtype=int)
    for t in res.trades:
        if t.exit_time is None:
            continue
        mask = (df.index >= t.entry_time) & (df.index <= t.exit_time)
        held[mask] = 1
    return held


def main():
    rows = []
    sigs: dict[str, pd.DataFrame] = {}
    helds: dict[str, pd.Series] = {}
    pnls: dict[str, pd.Series] = {}

    for sym, csv, set_path in SYMBOLS:
        if not (REPO / csv).exists() or not (REPO / set_path).exists():
            print(f"[skip] {sym}")
            continue
        df = pd.read_csv(REPO / csv, parse_dates=["time"]).set_index("time")
        s = load_set(REPO / set_path)
        p = make_params(s)
        p = replace(p, fee_rt_pct=0.04, slippage_pct=0.01, risk_pct=0.5)

        sigs[sym] = signal_series(df, p)
        helds[sym] = position_series(df, p)

        # 月次PnL系列 (equity の月次差分)
        res = backtest(df, p)
        if not res.equity.empty:
            monthly = res.equity.resample("ME").last().pct_change().dropna()
            pnls[sym] = monthly
        rows.append(dict(sym=sym))

    if len(sigs) < 2:
        print("Not enough symbols.")
        return

    # 1) シグナル同時発火 相関
    common_idx = None
    for s in sigs.values():
        common_idx = s.index if common_idx is None else common_idx.intersection(s.index)
    any_signals = pd.DataFrame({sym: sigs[sym].loc[common_idx, "any"]
                                 for sym in sigs})
    sig_corr = any_signals.corr()

    # 2) ポジション保有時間の重複
    held_df = pd.DataFrame({sym: helds[sym].reindex(common_idx, fill_value=0)
                             for sym in helds})
    held_overlap = held_df.corr()
    avg_concurrent = held_df.sum(axis=1).mean()  # 同時保有シンボル数の平均
    max_concurrent = int(held_df.sum(axis=1).max())

    # 3) 月次リターン相関
    if pnls:
        ret_df = pd.DataFrame(pnls).dropna(how="all")
        ret_corr = ret_df.corr()
    else:
        ret_corr = pd.DataFrame()

    # 4) 等重みポートフォリオの DD / Sharpe
    port_pnl = ret_df.fillna(0).mean(axis=1) if not ret_df.empty else pd.Series()
    if not port_pnl.empty:
        port_eq = (1 + port_pnl).cumprod()
        port_dd = ((port_eq - port_eq.cummax()) / port_eq.cummax()).min()
        port_sharpe = port_pnl.mean() / port_pnl.std() * math.sqrt(12) \
            if port_pnl.std() > 0 else 0.0
    else:
        port_dd = 0.0; port_sharpe = 0.0

    # 個別シンボルのDD/Sharpe
    individual = {}
    for sym, ret in pnls.items():
        eq = (1 + ret).cumprod()
        dd = ((eq - eq.cummax()) / eq.cummax()).min()
        sh = ret.mean() / ret.std() * math.sqrt(12) if ret.std() > 0 else 0.0
        individual[sym] = dict(dd=round(float(dd) * 100, 2),
                                sharpe=round(float(sh), 3),
                                avg_monthly_ret=round(float(ret.mean()) * 100, 3))

    print("\n=== 1) シグナル同時発火 相関 (any direction) ===")
    print(sig_corr.round(3).to_string())

    print("\n=== 2) ポジション保有時間 相関 ===")
    print(held_overlap.round(3).to_string())
    print(f"\n  平均同時保有シンボル数: {avg_concurrent:.2f}")
    print(f"  最大同時保有シンボル数: {max_concurrent}")

    print("\n=== 3) 月次リターン 相関 ===")
    print(ret_corr.round(3).to_string() if not ret_corr.empty else "(N/A)")

    print("\n=== 4) ポートフォリオ vs 個別 ===")
    print(f"{'symbol':12s}  avg_ret%/月   max DD%   Sharpe(年)")
    print("-" * 60)
    for sym, m in individual.items():
        print(f"{sym:12s}  {m['avg_monthly_ret']:>10.3f}   {m['dd']:>7.2f}   {m['sharpe']:>8.3f}")
    if not port_pnl.empty:
        print(f"{'PORTFOLIO':12s}  {port_pnl.mean()*100:>10.3f}   "
              f"{port_dd*100:>7.2f}   {port_sharpe:>8.3f}")

    out = dict(
        signal_corr=sig_corr.round(4).to_dict(),
        held_corr=held_overlap.round(4).to_dict(),
        avg_concurrent=round(float(avg_concurrent), 3),
        max_concurrent=max_concurrent,
        return_corr=ret_corr.round(4).to_dict() if not ret_corr.empty else {},
        individual=individual,
        portfolio=dict(avg_monthly_ret_pct=round(float(port_pnl.mean()) * 100, 3) if not port_pnl.empty else 0.0,
                        max_dd_pct=round(float(port_dd) * 100, 2),
                        sharpe=round(float(port_sharpe), 3)),
    )
    out_path = REPO / "results" / "cross_symbol_correlation.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nSaved -> {out_path}")


if __name__ == "__main__":
    main()
