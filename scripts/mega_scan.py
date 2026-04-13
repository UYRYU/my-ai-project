"""
100+ 戦略の大量スキャン。
XM Standard スプレッド + fee 10% で年率 10% 以上のものを抽出。
"""
from __future__ import annotations
import sys, os
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

import numpy as np, pandas as pd
from trading.strategies_v2 import *
from trading.backtest import _simulate_trade, _summarize

XM_STD = {"xauusd": 0.35, "xagusd": 0.035, "wtiusd": 0.05,
           "eurusd": 0.00017, "usdjpy": 0.016, "gbpusd": 0.00021,
           "btcusd": 5.0, "ethusd": 0.50}

ALL_ASSETS = {
    "xauusd": list(range(2015, 2019)),
    "xagusd": list(range(2015, 2019)),
    "wtiusd": list(range(2015, 2019)),
    "eurusd": list(range(2015, 2019)),
    "usdjpy": list(range(2015, 2019)),
    "gbpusd": list(range(2015, 2019)),
    "btcusd": list(range(2017, 2025)),
    "ethusd": list(range(2017, 2020)),
}

def load(pair, year):
    for p in [f"data/{pair}_15m_{year}.csv", f"data/{pair}_15m_{year}q1.csv"]:
        if os.path.exists(ROOT / p):
            df = pd.read_csv(ROOT / p, index_col=0, parse_dates=True)
            df.columns = [c.lower() for c in df.columns]
            return df
    return None

def resample(df, tf):
    if tf == "15min": return df
    return df.resample(tf).agg({"open":"first","high":"max","low":"min","close":"last"}).dropna()

def backtest_signals(df, signals, max_bars=500):
    trades = []
    in_pos = -1
    for sig in signals:
        if sig.entry_index <= in_pos: continue
        t = _simulate_trade(df, sig, max_bars=max_bars)
        if t is None: continue
        trades.append(t)
        exit_idx = df.index.get_loc(t.exit_time)
        if isinstance(exit_idx, slice): exit_idx = exit_idx.stop - 1
        in_pos = int(exit_idx)
    return trades

def wf_eval(asset, tf, signal_func, param_grid, risk_pct=0.02, fee=0.10):
    """Walk-forward: optimize on year N, test on year N+1."""
    years = ALL_ASSETS.get(asset, [])
    avail = [y for y in years if load(asset, y) is not None]
    if len(avail) < 2: return None

    spread = XM_STD.get(asset, 0)
    all_oos_trades = []

    for i in range(len(avail) - 1):
        is_y, oos_y = avail[i], avail[i+1]
        is_raw, oos_raw = load(asset, is_y), load(asset, oos_y)
        if is_raw is None or oos_raw is None: continue
        is_df = resample(is_raw, tf)
        oos_df = resample(oos_raw, tf)
        if len(is_df) < 100 or len(oos_df) < 100: continue

        # Optimize on IS
        best_params, best_r = None, -9999
        for params in param_grid:
            try:
                sigs = signal_func(is_df, **params)
                trades = backtest_signals(is_df, sigs)
                if len(trades) < 5: continue
                total_r = sum(t.pnl_r for t in trades)
                if total_r > best_r:
                    best_r = total_r
                    best_params = params
            except Exception:
                continue

        if best_params is None: continue

        # Test on OOS
        try:
            sigs = signal_func(oos_df, **best_params)
            trades = backtest_signals(oos_df, sigs)
        except Exception:
            continue

        for t in trades:
            sl_dist = abs(t.entry_price - t.stop)
            sr = spread / sl_dist if sl_dist > 0 else 0
            all_oos_trades.append((t.entry_time, t.pnl_r, sr))

    if not all_oos_trades: return None
    all_oos_trades.sort()

    # Sim with compound, fee
    eq = 1000.0; pk = eq; dd = 0.0; gp = 0.0; gl = 0.0
    for ts, pnl_r, sr in all_oos_trades:
        r_adj = pnl_r - sr
        if r_adj > 0: r_adj *= (1 - fee)
        delta = eq * risk_pct * r_adj
        eq += delta
        if r_adj > 0: gp += r_adj
        else: gl -= r_adj
        if eq > pk: pk = eq
        d = (pk - eq) / pk * 100 if pk > 0 else 0
        if d > dd: dd = d

    pf = gp / gl if gl > 0 else float('inf')
    n_folds = len(avail) - 1
    days = n_folds * 365
    ann = ((eq / 1000) ** (365 / days) - 1) * 100 if days > 0 and eq > 0 else -100
    monthly = len(all_oos_trades) / (days / 30)

    return {
        "eq": eq, "ann": ann, "dd": dd, "pf": pf,
        "trades": len(all_oos_trades), "folds": n_folds, "monthly": monthly,
    }


# -----------------------------------------------------------------------
# Parameter grids for each strategy
# -----------------------------------------------------------------------
def make_grids():
    rr_vals = [0.5, 1.0, 1.5, 2.0, 3.0]
    sw_vals = [10, 20, 30, 50]

    grids = {}

    # RSI
    for rsi_p in [7, 14]:
        for ema_p in [20, 50]:
            for rr in rr_vals:
                for sw in sw_vals:
                    for rsi_l, rsi_h in [(25, 75), (30, 70), (20, 80)]:
                        grids.setdefault("rsi", []).append(
                            dict(ema_period=ema_p, rsi_period=rsi_p, rsi_low=rsi_l, rsi_high=rsi_h,
                                 swing_lookback=sw, rr_ratio=rr))

    # Bollinger
    for bb_p in [15, 20, 30]:
        for bb_s in [1.5, 2.0, 2.5]:
            for ema_p in [20, 50]:
                for rr in rr_vals:
                    for sw in sw_vals:
                        grids.setdefault("bollinger", []).append(
                            dict(bb_period=bb_p, bb_std=bb_s, ema_period=ema_p,
                                 swing_lookback=sw, rr_ratio=rr))

    # EMA Cross
    for fast in [5, 10, 20]:
        for slow in [20, 50, 100]:
            if fast >= slow: continue
            for rr in rr_vals:
                for sw in sw_vals:
                    grids.setdefault("ema_cross", []).append(
                        dict(fast_ema=fast, slow_ema=slow, swing_lookback=sw, rr_ratio=rr))

    # Breakout
    for lb in [10, 20, 50]:
        for rr in rr_vals:
            for sw in sw_vals:
                grids.setdefault("breakout", []).append(
                    dict(lookback=lb, swing_lookback=sw, rr_ratio=rr))

    # MACD
    for fast, slow, sig in [(12,26,9), (8,21,5), (5,13,3)]:
        for ema_t in [20, 50]:
            for rr in rr_vals:
                for sw in sw_vals:
                    grids.setdefault("macd", []).append(
                        dict(fast=fast, slow=slow, signal_period=sig, ema_trend=ema_t,
                             swing_lookback=sw, rr_ratio=rr))

    # Mean Reversion
    for ema_p in [10, 20, 50]:
        for thresh in [0.5, 1.0, 1.5, 2.0]:
            for rr in [0.5, 1.0, 1.5]:
                for sw in sw_vals:
                    grids.setdefault("mean_rev", []).append(
                        dict(ema_period=ema_p, threshold_pct=thresh,
                             swing_lookback=sw, rr_ratio=rr))

    # RSI + BB combo
    for rsi_p in [7, 14]:
        for rsi_l, rsi_h in [(25,75), (30,70)]:
            for bb_p in [15, 20]:
                for bb_s in [1.5, 2.0]:
                    for rr in rr_vals:
                        for sw in sw_vals:
                            grids.setdefault("rsi_bb", []).append(
                                dict(rsi_period=rsi_p, rsi_low=rsi_l, rsi_high=rsi_h,
                                     bb_period=bb_p, bb_std=bb_s,
                                     swing_lookback=sw, rr_ratio=rr))

    return grids

SIGNAL_FUNCS = {
    "rsi": signals_rsi,
    "bollinger": signals_bollinger,
    "ema_cross": signals_ema_cross,
    "breakout": signals_breakout,
    "macd": signals_macd,
    "mean_rev": signals_mean_reversion,
    "rsi_bb": signals_rsi_bb,
}


def main():
    grids = make_grids()
    timeframes = ["15min", "30min", "1h", "4h"]

    total_combos = sum(
        len(ALL_ASSETS) * len(timeframes)
        for _ in grids
    )
    print(f"Strategies: {len(grids)} types, {total_combos} asset×tf combos")
    print(f"Scanning...\n", flush=True)

    winners = []
    scanned = 0

    for strat_name, param_grid in grids.items():
        func = SIGNAL_FUNCS[strat_name]
        for asset in ALL_ASSETS:
            for tf in timeframes:
                scanned += 1
                if scanned % 20 == 0:
                    print(f"  {scanned}/{total_combos} ({len(winners)} winners)...", flush=True)

                result = wf_eval(asset, tf, func, param_grid)
                if result is None: continue
                if result["ann"] < 10: continue  # 年率 10% 未満は除外
                if result["trades"] < 10: continue

                label = f"{strat_name}/{asset.upper()}/{tf}"
                winners.append({"label": label, "strat": strat_name,
                               "asset": asset, "tf": tf, **result})

    # Sort by annual return
    winners.sort(key=lambda x: x["ann"], reverse=True)

    print(f"\n{'='*100}")
    print(f"XM Standard + fee10% で年率 10%+ : {len(winners)} 個発見")
    print(f"{'='*100}\n")

    print(f"{'#':>3} {'label':<30} {'folds':>5} {'trades':>7} {'t/月':>5} {'ann%':>7} {'DD':>7} {'PF':>6} {'$final':>8}")
    print("-" * 90)
    for i, w in enumerate(winners[:60], 1):
        print(f"{i:>3} {w['label']:<30} {w['folds']:>5} {w['trades']:>7} {w['monthly']:>5.1f} {w['ann']:>+6.1f}% {w['dd']:>6.1f}% {w['pf']:>6.2f} ${w['eq']:>7.0f}")

    if len(winners) > 60:
        print(f"  ... + {len(winners)-60} more")

    # 戦略タイプ別集計
    print(f"\n=== 戦略タイプ別 ===")
    by_type = {}
    for w in winners:
        by_type.setdefault(w["strat"], []).append(w)
    for st, ws in sorted(by_type.items(), key=lambda x: -len(x[1])):
        anns = [w["ann"] for w in ws]
        print(f"  {st:<15}: {len(ws):>3} 個  ann avg={np.mean(anns):+.1f}% max={max(anns):+.1f}%")

    return 0

if __name__ == "__main__":
    sys.exit(main())
