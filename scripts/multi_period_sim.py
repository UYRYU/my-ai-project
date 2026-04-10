"""
マルチ期間バックテスト + $1000 複利シミュレーション

実データの各期間 (2015Q1/2016Q1/2017Q1/2018Q1/2018Q2) で
real-best 設定 (swing SL / rr=1.0 TP / swing_lookback=30) を評価し、
$1000 スタート + 2% リスク複利 + スプレッド $0.30 で最終資金を計算する。

実行: PYTHONPATH=. python3 scripts/multi_period_sim.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# プロジェクトルートを sys.path に追加 (PYTHONPATH 設定なしで実行可能に)
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from trading.backtest import run_backtest
from trading.data import load_csv


PARAMS = dict(
    sl_mode="swing",
    tp_mode="rr",
    rr_ratio=1.0,
    swing_lookback=30,
)


def compound_sim(trades, start_capital: float, risk_pct: float, spread: float) -> dict:
    """ロットは risk_pct から逆算、最小 0.01 ロット未満はスキップ。"""
    eq = start_capital
    peak = eq
    max_dd = 0.0
    taken = 0
    skipped = 0
    for t in trades:
        sl_dist = abs(t.entry_price - t.stop)
        if sl_dist <= 0:
            skipped += 1
            continue
        risk_amount = eq * risk_pct
        needed_lot = risk_amount / (sl_dist * 100)
        lot = round(needed_lot, 2)
        if lot < 0.01:
            skipped += 1
            continue
        price_move = (t.exit_price - t.entry_price) if t.side == "long" else (t.entry_price - t.exit_price)
        pnl = price_move * 100 * lot - spread * 100 * lot
        eq += pnl
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
        taken += 1
        if eq <= 0:
            return dict(final=0.0, max_dd=max_dd, taken=taken, skipped=skipped, busted=True)
    return dict(final=eq, max_dd=max_dd, taken=taken, skipped=skipped, busted=False)


def main() -> int:
    periods = [
        ("2015Q1", "data/xauusd_15m_2015q1.csv"),
        ("2016Q1", "data/xauusd_15m_2016q1.csv"),
        ("2017Q1", "data/xauusd_15m_2017q1.csv"),
        ("2018Q1", "data/xauusd_15m_2018q1.csv"),
        ("2018Q2", "data/xauusd_15m_2018q2.csv"),
    ]
    start_capital = 1000.0
    risk_pct = 0.02
    spread = 0.30

    print(f"=== Multi-period validation: swing/rr=1.0/sw=30 ===")
    print(f"Start: ${start_capital:.0f}  Risk: {risk_pct*100:.0f}%/trade  Spread: ${spread:.2f}\n")

    header = (
        f"{'period':<8} {'bars':>5} {'days':>5} "
        f"{'trades':>6} {'win%':>6} {'avgR':>7} {'totR':>7} {'PF':>5} {'ddR':>6} "
        f"{'final':>10} {'return':>9} {'monthly':>9} {'maxDD':>7}"
    )
    print(header)
    print("-" * len(header))

    aggregate = {"total_r": 0.0, "wins": 0, "losses": 0, "trades": 0, "days": 0.0}
    final_usd = start_capital
    combined = start_capital  # 全期間つないだ複利

    rows = []
    for label, path in periods:
        if not Path(path).exists():
            print(f"{label}: missing {path}")
            continue
        df = load_csv(path)
        days = (df.index[-1] - df.index[0]).total_seconds() / 86400
        trades, stats = run_backtest(df, **PARAMS)
        sim = compound_sim(trades, start_capital=start_capital, risk_pct=risk_pct, spread=spread)
        ret_pct = (sim["final"] / start_capital - 1) * 100 if sim["final"] > 0 else -100
        monthly = ((sim["final"] / start_capital) ** (30 / days) - 1) * 100 if sim["final"] > 0 else -100

        # 各期間独立の $1000 スタート
        rows.append((label, len(df), days, stats, sim, ret_pct, monthly))

        # 全期間つなぎ (期末残高を次期の初期資金に)
        combined_sim = compound_sim(trades, start_capital=combined, risk_pct=risk_pct, spread=spread)
        combined = combined_sim["final"] if combined_sim["final"] > 0 else combined

        aggregate["total_r"] += stats["total_r"]
        aggregate["wins"] += stats["wins"]
        aggregate["losses"] += stats["losses"]
        aggregate["trades"] += stats["trades"]
        aggregate["days"] += days

        print(
            f"{label:<8} {len(df):>5} {days:>5.0f} "
            f"{stats['trades']:>6} {stats['win_rate']*100:>5.1f}% "
            f"{stats['avg_r']:>+7.3f} {stats['total_r']:>+7.2f} {stats['profit_factor']:>5.2f} "
            f"{stats['max_dd_r']:>6.2f} "
            f"${sim['final']:>8.2f} {ret_pct:>+7.1f}% {monthly:>+7.1f}% {sim['max_dd']:>6.1f}%"
        )

    print("-" * len(header))
    total_days = aggregate["days"]
    total_trades = aggregate["trades"]
    print(
        f"{'TOTAL':<8} {'':>5} {total_days:>5.0f} {total_trades:>6} "
        f"{aggregate['wins']/total_trades*100:>5.1f}% "
        f"{aggregate['total_r']/total_trades:>+7.3f} {aggregate['total_r']:>+7.2f}"
    )
    print()
    print(f"=== 全期間 $1000 連結複利 (期末残高を次期に繰越) ===")
    combined_ret = (combined / start_capital - 1) * 100
    combined_annual = ((combined / start_capital) ** (365 / total_days) - 1) * 100
    print(f"  final: ${combined:.2f}")
    print(f"  total return: {combined_ret:+.1f}% over {total_days:.0f} days")
    print(f"  annualized (compound): {combined_annual:+.1f}% / yr")
    print(f"  avg monthly: {((combined/start_capital)**(30/total_days) - 1)*100:+.1f}% / month")

    # 年率R換算
    print()
    print(f"=== R ベース集計 ===")
    avg_annual_r = aggregate["total_r"] * 365 / total_days
    print(f"  total R: {aggregate['total_r']:+.2f}")
    print(f"  trades/month (avg): {total_trades / total_days * 30:.0f}")
    print(f"  avg win rate: {aggregate['wins']/total_trades*100:.1f}%")
    print(f"  annualized R: {avg_annual_r:+.1f} R / yr")

    return 0


if __name__ == "__main__":
    sys.exit(main())
