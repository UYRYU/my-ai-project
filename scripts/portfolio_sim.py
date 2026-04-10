"""
マルチペアポートフォリオ シミュレーション

$1000 を N ペアに均等配分し、各ペアの最適パラメータで独立に 2% リスク複利。
ペア間で資金は共有しない (独立口座モデル)。

実行: python3 scripts/portfolio_sim.py
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
PAIR_CONFIGS = {
    "XAUUSD": dict(path="data/xauusd_15m_2018q1.csv", rr_ratio=2.0, swing_lookback=20),
    "EURUSD": dict(path="data/eurusd_15m_2018q1.csv",  rr_ratio=1.0, swing_lookback=50),
    "USDJPY": dict(path="data/usdjpy_15m_2018q1.csv",  rr_ratio=1.5, swing_lookback=10),
    "GBPUSD": dict(path="data/gbpusd_15m_2018q1.csv",  rr_ratio=2.0, swing_lookback=50),
}


def compound_sim(trades, start_capital: float, risk_pct: float, spread_pct: float = 0.0) -> dict:
    """
    ロットは risk_pct から逆算。最小ロット制約なし (理論値)。
    spread_pct はリスク距離に対するスプレッド比率 (例: 0.05 = 5%)。
    """
    eq = start_capital
    peak = eq
    max_dd = 0.0
    for t in trades:
        risk = abs(t.entry_price - t.stop)
        if risk <= 0:
            continue
        risk_amount = eq * risk_pct
        pnl_r_adj = t.pnl_r - spread_pct  # スプレッドを R 単位で差し引く
        delta = risk_amount * pnl_r_adj
        eq += delta
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
        if eq <= 0:
            return dict(final=0.0, max_dd=max_dd, busted=True)
    return dict(final=eq, max_dd=max_dd, busted=False)


def main() -> int:
    total_capital = 1000.0
    risk_pct = 0.02
    spread_r = 0.05  # 1R あたり 5% 相当のスプレッドコスト

    n_pairs = len(PAIR_CONFIGS)
    capital_per_pair = total_capital / n_pairs

    print(f"=== Multi-pair portfolio: ${total_capital:.0f} / {n_pairs} pairs ===")
    print(f"Capital per pair: ${capital_per_pair:.0f}  Risk: {risk_pct*100:.0f}%  Spread: {spread_r*100:.0f}% of 1R\n")

    header = f"{'pair':<8} {'params':<20} {'trades':>6} {'win%':>6} {'avgR':>7} {'totR':>8} {'PF':>6} {'$start':>8} {'$final':>8} {'ret%':>8} {'maxDD':>7}"
    print(header)
    print("-" * len(header))

    total_trades = 0
    total_final = 0.0
    all_trades_tagged = []  # (timestamp, pnl_r, pair) for combined equity

    for pair, cfg in PAIR_CONFIGS.items():
        df = load_csv(cfg["path"])
        trades, stats = run_backtest(
            df, sl_mode="swing", tp_mode="rr",
            rr_ratio=cfg["rr_ratio"], swing_lookback=cfg["swing_lookback"],
        )
        sim = compound_sim(trades, capital_per_pair, risk_pct, spread_r)
        ret = (sim["final"] / capital_per_pair - 1) * 100

        total_trades += stats["trades"]
        total_final += sim["final"]
        for t in trades:
            all_trades_tagged.append((t.entry_time, t.pnl_r, pair))

        params = f"rr={cfg['rr_ratio']:<4} sw={cfg['swing_lookback']}"
        print(
            f"{pair:<8} {params:<20} {stats['trades']:>6} {stats['win_rate']*100:>5.1f}% "
            f"{stats['avg_r']:>+7.3f} {stats['total_r']:>+8.2f} {stats['profit_factor']:>6.2f} "
            f"${capital_per_pair:>7.0f} ${sim['final']:>7.2f} {ret:>+7.1f}% {sim['max_dd']:>6.1f}%"
        )

    print("-" * len(header))
    port_ret = (total_final / total_capital - 1) * 100
    print(f"{'PORTFOLIO':<8} {'':20} {total_trades:>6} {'':>6} {'':>7} {'':>8} {'':>6} ${total_capital:>7.0f} ${total_final:>7.2f} {port_ret:>+7.1f}%")

    # 日付順に全トレードを並べて combined equity curve
    all_trades_tagged.sort(key=lambda x: x[0])
    eq = total_capital
    peak = eq
    max_dd_pct = 0.0
    eq_curve = [(None, eq)]
    for ts, pnl_r, pair in all_trades_tagged:
        delta = (eq / n_pairs) * risk_pct * (pnl_r - spread_r)
        eq += delta
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100
        if dd > max_dd_pct:
            max_dd_pct = dd
        eq_curve.append((ts, eq))

    # 期間計算
    first_ts = all_trades_tagged[0][0]
    last_ts = all_trades_tagged[-1][0]
    days = (last_ts - first_ts).total_seconds() / 86400

    combined_ret = (eq / total_capital - 1) * 100
    ann = ((eq / total_capital) ** (365 / days) - 1) * 100 if days > 0 else 0
    monthly = ((eq / total_capital) ** (30 / days) - 1) * 100 if days > 0 else 0

    print(f"\n=== Combined equity (trades interleaved by time) ===")
    print(f"  Period: {first_ts.date()} -> {last_ts.date()} ({days:.0f} days)")
    print(f"  Total trades: {total_trades} ({total_trades*30/days:.0f}/month)")
    print(f"  Final: ${eq:.2f}")
    print(f"  Return: {combined_ret:+.1f}%")
    print(f"  Monthly: {monthly:+.1f}%")
    print(f"  Annual (compound): {ann:+.1f}%")
    print(f"  Max DD: {max_dd_pct:.1f}%")

    return 0


if __name__ == "__main__":
    sys.exit(main())
