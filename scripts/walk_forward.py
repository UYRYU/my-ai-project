"""
ウォークフォワード分析

XAUUSD 年間データ (2011-2018) を使い、
  In-sample  : 1 年分で最適化
  Out-of-sample: 次の 1 年分で検証
をスライドしながら繰り返す。

実行: python3 scripts/walk_forward.py
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


# グリッド: swing SL × RR TP
RR_VALUES = [0.5, 0.8, 1.0, 1.2, 1.5, 2.0, 2.5, 3.0]
SW_VALUES = [10, 15, 20, 30, 50]


def optimize_on(df: pd.DataFrame, min_trades: int = 20) -> tuple[float, int, dict]:
    """df 上で total_r を最大化するパラメータを探す。"""
    best_rr, best_sw, best_stats = 1.0, 20, None
    best_r = -9999
    for sw in SW_VALUES:
        for rr in RR_VALUES:
            _, stats = run_backtest(
                df, sl_mode="swing", tp_mode="rr",
                rr_ratio=rr, swing_lookback=sw,
            )
            if stats["trades"] >= min_trades and stats["total_r"] > best_r:
                best_r = stats["total_r"]
                best_rr, best_sw, best_stats = rr, sw, stats
    return best_rr, best_sw, best_stats


def evaluate_on(df: pd.DataFrame, rr: float, sw: int) -> dict:
    """指定パラメータで df 上のバックテスト結果を返す。"""
    _, stats = run_backtest(
        df, sl_mode="swing", tp_mode="rr",
        rr_ratio=rr, swing_lookback=sw,
    )
    return stats


def load_year_data(year: int) -> pd.DataFrame | None:
    """年間データまたは Q1 データを読み込む。"""
    candidates = [
        f"data/xauusd_15m_{year}.csv",       # 年間
        f"data/xauusd_15m_{year}q1.csv",      # Q1
    ]
    for c in candidates:
        p = ROOT / c
        if p.exists():
            return load_csv(str(p))
    return None


def main() -> int:
    years = list(range(2011, 2019))

    # データ読み込み
    data: dict[int, pd.DataFrame] = {}
    for y in years:
        df = load_year_data(y)
        if df is not None:
            data[y] = df
            print(f"  {y}: {len(df)} bars ({df.index[0].date()} -> {df.index[-1].date()})")
        else:
            print(f"  {y}: NOT FOUND")

    available = sorted(data.keys())
    if len(available) < 2:
        print("Need at least 2 years of data for walk-forward.")
        return 1

    print(f"\nAvailable years: {available}")
    print()

    # Walk-forward: IS=year[i], OOS=year[i+1]
    print("=" * 100)
    header = (
        f"{'IS year':<10} {'IS best':<14} {'IS trades':>9} {'IS totR':>8} {'IS PF':>7} "
        f"{'OOS year':<10} {'OOS trades':>10} {'OOS totR':>9} {'OOS PF':>8} {'OOS win%':>9}"
    )
    print(header)
    print("-" * 100)

    oos_total_r = 0.0
    oos_total_trades = 0
    oos_wins = 0
    n_folds = 0

    for i in range(len(available) - 1):
        is_year = available[i]
        oos_year = available[i + 1]

        # in-sample 最適化
        rr, sw, is_stats = optimize_on(data[is_year])
        if is_stats is None:
            print(f"  {is_year}: no valid combo found")
            continue

        # out-of-sample 検証
        oos_stats = evaluate_on(data[oos_year], rr, sw)

        oos_total_r += oos_stats["total_r"]
        oos_total_trades += oos_stats["trades"]
        oos_wins += oos_stats["wins"]
        n_folds += 1

        print(
            f"{is_year:<10} rr={rr:<4} sw={sw:<4} {is_stats['trades']:>9} "
            f"{is_stats['total_r']:>+8.2f} {is_stats['profit_factor']:>7.2f} "
            f"{oos_year:<10} {oos_stats['trades']:>10} "
            f"{oos_stats['total_r']:>+9.2f} {oos_stats['profit_factor']:>8.2f} "
            f"{oos_stats['win_rate']*100:>8.1f}%"
        )

    print("-" * 100)
    if n_folds > 0:
        avg_oos_r = oos_total_r / n_folds
        avg_oos_wr = oos_wins / oos_total_trades * 100 if oos_total_trades > 0 else 0
        print(f"\n=== Walk-forward summary ({n_folds} folds) ===")
        print(f"  OOS total R: {oos_total_r:+.2f}")
        print(f"  OOS avg R per fold: {avg_oos_r:+.2f}")
        print(f"  OOS total trades: {oos_total_trades}")
        print(f"  OOS avg win rate: {avg_oos_wr:.1f}%")

        positive_folds = sum(1 for i in range(len(available)-1)
                           if evaluate_on(data[available[i+1]],
                                         *optimize_on(data[available[i]])[:2])["total_r"] > 0)
        print(f"  OOS profitable folds: {positive_folds}/{n_folds}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
