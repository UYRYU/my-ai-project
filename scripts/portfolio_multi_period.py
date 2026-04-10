"""
マルチ期間 × マルチペアポートフォリオ検証

各年で 4 ペア (XAUUSD/EURUSD/USDJPY/GBPUSD) を
2018Q1 で最適化したパラメータで同時に走らせ、
$1000 / 4 分割 / リスク 2% / スプレッド 5% of 1R で複利シミュレーション。

実行: python3 scripts/portfolio_multi_period.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from trading.backtest import run_backtest
from trading.data import load_csv


# 各ペアの最適パラメータ (2018Q1 で最適化)
PAIR_PARAMS = {
    "XAUUSD": dict(rr_ratio=2.0, swing_lookback=20),
    "EURUSD": dict(rr_ratio=1.0, swing_lookback=50),
    "USDJPY": dict(rr_ratio=1.5, swing_lookback=10),
    "GBPUSD": dict(rr_ratio=2.0, swing_lookback=50),
}


def find_data(pair: str, period: str) -> str | None:
    """data/ からファイルを探す。"""
    pair_lower = pair.lower()
    candidates = [
        f"data/{pair_lower}_15m_{period}.csv",
        f"data/{pair_lower}_15m_{period}q1.csv",
    ]
    for c in candidates:
        p = ROOT / c
        if p.exists():
            return str(p)
    return None


def compound_sim_trades(trades, start_capital: float, risk_pct: float, spread_r: float) -> dict:
    eq = start_capital
    peak = eq
    max_dd = 0.0
    for t in trades:
        risk = abs(t.entry_price - t.stop)
        if risk <= 0:
            continue
        risk_amount = eq * risk_pct
        delta = risk_amount * (t.pnl_r - spread_r)
        eq += delta
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
        if eq <= 0:
            return dict(final=0.0, max_dd=max_dd)
    return dict(final=eq, max_dd=max_dd)


def run_period(period: str, total_capital: float, risk_pct: float, spread_r: float) -> dict | None:
    """1 期間の 4 ペアポートフォリオ結果を返す。"""
    n_pairs = len(PAIR_PARAMS)
    cap_per_pair = total_capital / n_pairs

    pair_results = {}
    all_trades = []  # (timestamp, pnl_r, pair)
    total_days = 0.0

    for pair, params in PAIR_PARAMS.items():
        path = find_data(pair, period)
        if path is None:
            return None  # データ不足
        df = load_csv(path)
        days = (df.index[-1] - df.index[0]).total_seconds() / 86400
        if days > total_days:
            total_days = days

        trades, stats = run_backtest(df, sl_mode="swing", tp_mode="rr", **params)
        sim = compound_sim_trades(trades, cap_per_pair, risk_pct, spread_r)

        pair_results[pair] = {
            "trades": stats["trades"],
            "win_rate": stats["win_rate"],
            "total_r": stats["total_r"],
            "pf": stats["profit_factor"],
            "final": sim["final"],
            "max_dd": sim["max_dd"],
        }
        for t in trades:
            all_trades.append((t.entry_time, t.pnl_r, pair))

    # Combined equity (interleaved)
    all_trades.sort(key=lambda x: x[0])
    eq = total_capital
    peak = eq
    max_dd_combined = 0.0
    for ts, pnl_r, pair in all_trades:
        delta = (eq / n_pairs) * risk_pct * (pnl_r - spread_r)
        eq += delta
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100 if peak > 0 else 0
        if dd > max_dd_combined:
            max_dd_combined = dd

    total_trades = sum(r["trades"] for r in pair_results.values())
    total_final_independent = sum(r["final"] for r in pair_results.values())

    return {
        "period": period,
        "days": total_days,
        "pairs": pair_results,
        "total_trades": total_trades,
        "combined_final": eq,
        "combined_dd": max_dd_combined,
        "independent_final": total_final_independent,
    }


def main() -> int:
    total_capital = 1000.0
    risk_pct = 0.02
    spread_r = 0.05

    periods = ["2015", "2016", "2017", "2018"]

    print(f"=== 4-pair portfolio: ${total_capital:.0f} / risk {risk_pct*100:.0f}% / spread {spread_r*100:.0f}% of 1R ===")
    print(f"Params optimized on 2018Q1 (in-sample). All other periods are OOS.\n")

    # Header
    print(f"{'period':<8} {'days':>5} | ", end="")
    for pair in PAIR_PARAMS:
        print(f"{pair:>8} ", end="")
    print(f"| {'trades':>7} {'$final':>8} {'ret%':>8} {'monthly':>8} {'maxDD':>7}")
    print("-" * 110)

    connected_eq = total_capital
    all_period_results = []

    for period in periods:
        result = run_period(period, total_capital, risk_pct, spread_r)
        if result is None:
            print(f"{period:<8} -- data incomplete, skip --")
            continue

        all_period_results.append(result)
        days = result["days"]
        eq = result["combined_final"]
        ret = (eq / total_capital - 1) * 100
        monthly = ((eq / total_capital) ** (30 / days) - 1) * 100 if days > 0 else 0

        # Connected equity
        conn_result = run_period(period, connected_eq, risk_pct, spread_r)
        if conn_result:
            connected_eq = conn_result["combined_final"]

        print(f"{period:<8} {days:>5.0f} | ", end="")
        for pair in PAIR_PARAMS:
            pr = result["pairs"][pair]
            print(f"{pr['total_r']:>+7.1f}R ", end="")
        print(f"| {result['total_trades']:>7} ${eq:>7.0f} {ret:>+7.1f}% {monthly:>+6.1f}%/m {result['combined_dd']:>6.1f}%")

    print("-" * 110)

    if all_period_results:
        total_days = sum(r["days"] for r in all_period_results)
        total_r_all = sum(
            sum(pr["total_r"] for pr in r["pairs"].values())
            for r in all_period_results
        )
        total_trades_all = sum(r["total_trades"] for r in all_period_results)

        conn_ret = (connected_eq / total_capital - 1) * 100
        conn_ann = ((connected_eq / total_capital) ** (365 / total_days) - 1) * 100 if total_days > 0 else 0
        conn_monthly = ((connected_eq / total_capital) ** (30 / total_days) - 1) * 100 if total_days > 0 else 0

        print(f"\n=== Connected equity ($1000 → period end → next period start) ===")
        print(f"  Periods: {len(all_period_results)} ({total_days:.0f} days total)")
        print(f"  Total trades: {total_trades_all} ({total_trades_all*30/total_days:.0f}/month)")
        print(f"  Total R (all pairs): {total_r_all:+.1f}")
        print(f"  Final: ${connected_eq:.2f}")
        print(f"  Return: {conn_ret:+.1f}%")
        print(f"  Monthly: {conn_monthly:+.1f}%")
        print(f"  Annual (compound): {conn_ann:+.1f}%")

        # per-pair breakdown across all periods
        print(f"\n=== Per-pair total R across all periods ===")
        for pair in PAIR_PARAMS:
            pair_total_r = sum(r["pairs"][pair]["total_r"] for r in all_period_results)
            pair_total_trades = sum(r["pairs"][pair]["trades"] for r in all_period_results)
            print(f"  {pair:<8}: {pair_total_r:>+8.1f} R  ({pair_total_trades} trades)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
