"""Walk-forward validation runner.

Splits the full period into rolling (IS, OOS) windows, runs strategy
optimization on IS, evaluates on both IS and OOS, then aggregates metrics
across windows to detect overfitting.

See SKILL.md for the contract and pass/fail rules.
"""

from __future__ import annotations

import argparse
import calendar
import csv
import importlib.util
import json
import math
import statistics
import sys
from datetime import datetime
from pathlib import Path


OVERFIT_RULES = {
    "is_oos_pf_ratio_max": 2.0,
    "oos_pf_below_one_share_max": 0.5,
}

INSTABILITY_OOS_PF_STDDEV = 1.0


def add_months(d: datetime, months: int) -> datetime:
    m = d.month - 1 + months
    year = d.year + m // 12
    month = m % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return d.replace(year=year, month=month, day=day)


def make_windows(start: datetime, end: datetime, is_m: int, oos_m: int, step_m: int) -> list[dict]:
    windows: list[dict] = []
    is_start = start
    while True:
        is_end = add_months(is_start, is_m)
        oos_start = is_end
        oos_end = add_months(oos_start, oos_m)
        if oos_end > end:
            break
        windows.append({
            "is_start": is_start,
            "is_end": is_end,
            "oos_start": oos_start,
            "oos_end": oos_end,
        })
        is_start = add_months(is_start, step_m)
    return windows


def load_strategy(path: Path):
    spec = importlib.util.spec_from_file_location("user_strategy", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load strategy from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "Strategy"):
        raise AttributeError(f"{path} does not define a `Strategy` class")
    cls = module.Strategy
    for required in ("optimize", "set_params", "backtest"):
        if not hasattr(cls, required):
            raise AttributeError(
                f"Strategy must implement `{required}` for walk-forward "
                f"(see .claude/skills/walk-forward/SKILL.md)"
            )
    return cls


def parse_period(period: str) -> tuple[datetime, datetime]:
    s, e = period.split(":")
    return datetime.fromisoformat(s), datetime.fromisoformat(e)


def fmt_period(start: datetime, end: datetime) -> str:
    return f"{start.date().isoformat()}:{end.date().isoformat()}"


def compute_metrics(trades: list[dict], equity: list[float], period: str) -> dict:
    n = len(trades)
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    win_rate = len(wins) / n if n else 0.0
    gp = sum(wins)
    gl = abs(sum(losses))
    if gl > 0:
        pf: float | None = gp / gl
    elif gp > 0:
        pf = None  # treat infinite PF as None for serialization
    else:
        pf = 0.0
    ev = sum(pnls) / n if n else 0.0
    total_ret = (equity[-1] / equity[0] - 1.0) if equity and equity[0] else 0.0

    peak = equity[0] if equity else 0.0
    max_dd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak
            if dd > max_dd:
                max_dd = dd

    start, end = parse_period(period)
    duration_years = max((end - start).days / 365.25, 1e-9)
    trades_per_year = n / duration_years
    if n > 1:
        rets = []
        for i, t in enumerate(trades):
            base = equity[i] if equity[i] else 1.0
            rets.append(t["pnl"] / base)
        mean_r = sum(rets) / len(rets)
        var = sum((r - mean_r) ** 2 for r in rets) / (len(rets) - 1)
        std_r = math.sqrt(var)
        sharpe = (mean_r / std_r) * math.sqrt(trades_per_year) if std_r > 0 else 0.0
    else:
        sharpe = 0.0

    return {
        "num_trades": n,
        "win_rate": round(win_rate, 4),
        "profit_factor": round(pf, 4) if isinstance(pf, float) else None,
        "max_drawdown": round(max_dd, 4),
        "sharpe": round(sharpe, 4),
        "expected_value": round(ev, 4),
        "total_return": round(total_ret, 4),
        "final_equity": round(equity[-1], 4) if equity else 0.0,
    }


def run_window(strategy, w: dict, capital: float) -> dict:
    is_p = fmt_period(w["is_start"], w["is_end"])
    oos_p = fmt_period(w["oos_start"], w["oos_end"])
    params = strategy.optimize(is_p, capital)
    strategy.set_params(params)
    is_trades, is_eq = strategy.backtest(is_p, capital)
    oos_trades, oos_eq = strategy.backtest(oos_p, capital)
    return {
        "is_period": is_p,
        "oos_period": oos_p,
        "params": params,
        "is_metrics": compute_metrics(is_trades, is_eq, is_p),
        "oos_metrics": compute_metrics(oos_trades, oos_eq, oos_p),
        "oos_trades": oos_trades,
    }


def combine_oos(window_results: list[dict], capital: float, full_oos_period: str):
    all_trades: list[dict] = []
    equity: list[float] = [capital]
    bal = capital
    for w in window_results:
        for t in w["oos_trades"]:
            bal += t["pnl"]
            equity.append(round(bal, 4))
            all_trades.append(t)
    return all_trades, equity, compute_metrics(all_trades, equity, full_oos_period)


def stability_and_overfit(window_results: list[dict]) -> dict:
    is_pfs = [w["is_metrics"]["profit_factor"] for w in window_results
              if w["is_metrics"]["profit_factor"] is not None]
    oos_pfs = [w["oos_metrics"]["profit_factor"] for w in window_results
               if w["oos_metrics"]["profit_factor"] is not None]

    mean_is = statistics.mean(is_pfs) if is_pfs else 0.0
    mean_oos = statistics.mean(oos_pfs) if oos_pfs else 0.0
    oos_pf_std = statistics.pstdev(oos_pfs) if len(oos_pfs) > 1 else 0.0
    degradation = ((mean_is - mean_oos) / mean_is) if mean_is else 0.0
    bad_oos = sum(1 for p in oos_pfs if p < 1.0)
    bad_share = bad_oos / len(oos_pfs) if oos_pfs else 1.0

    fails: list[str] = []
    if mean_oos > 0 and (mean_is / mean_oos) > OVERFIT_RULES["is_oos_pf_ratio_max"]:
        fails.append(
            f"mean(IS PF)/mean(OOS PF) = {mean_is/mean_oos:.2f} "
            f"> {OVERFIT_RULES['is_oos_pf_ratio_max']}"
        )
    if bad_share > OVERFIT_RULES["oos_pf_below_one_share_max"]:
        fails.append(
            f"OOS PF < 1.0 in {bad_oos}/{len(oos_pfs)} windows ({bad_share:.0%})"
        )

    warns: list[str] = []
    if oos_pf_std > INSTABILITY_OOS_PF_STDDEV:
        warns.append(f"OOS PF stddev = {oos_pf_std:.2f} (不安定)")

    return {
        "mean_is_pf": round(mean_is, 4),
        "mean_oos_pf": round(mean_oos, 4),
        "oos_pf_stddev": round(oos_pf_std, 4),
        "is_oos_degradation": round(degradation, 4),
        "fails": fails,
        "warns": warns,
        "passed": len(fails) == 0,
    }


def write_outputs(out_dir: Path, summary: dict, window_results: list[dict],
                  combined_equity: list[float]) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=str)
    )
    written.append("summary.json")

    pw_path = out_dir / "per_window.csv"
    fieldnames = [
        "window", "is_start", "is_end", "oos_start", "oos_end", "params",
        "is_num_trades", "is_win_rate", "is_pf", "is_sharpe",
        "oos_num_trades", "oos_win_rate", "oos_pf", "oos_sharpe",
    ]
    with pw_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for i, w in enumerate(window_results):
            ism = w["is_metrics"]
            oosm = w["oos_metrics"]
            is_s, is_e = w["is_period"].split(":")
            oos_s, oos_e = w["oos_period"].split(":")
            writer.writerow({
                "window": i + 1,
                "is_start": is_s,
                "is_end": is_e,
                "oos_start": oos_s,
                "oos_end": oos_e,
                "params": json.dumps(w["params"], ensure_ascii=False),
                "is_num_trades": ism["num_trades"],
                "is_win_rate": ism["win_rate"],
                "is_pf": ism["profit_factor"],
                "is_sharpe": ism["sharpe"],
                "oos_num_trades": oosm["num_trades"],
                "oos_win_rate": oosm["win_rate"],
                "oos_pf": oosm["profit_factor"],
                "oos_sharpe": oosm["sharpe"],
            })
    written.append("per_window.csv")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig1, ax1 = plt.subplots(figsize=(10, 5))
        ax1.plot(range(len(combined_equity)), combined_equity, linewidth=1.2)
        ax1.set_title("Combined OOS Equity Curve")
        ax1.set_xlabel("OOS Trade #")
        ax1.set_ylabel("Equity")
        ax1.grid(True, alpha=0.3)
        fig1.tight_layout()
        fig1.savefig(out_dir / "combined_equity.png", dpi=120)
        plt.close(fig1)
        written.append("combined_equity.png")

        fig2, ax2 = plt.subplots(figsize=(10, 5))
        x = list(range(1, len(window_results) + 1))
        is_pfs = [(w["is_metrics"]["profit_factor"] or 0.0) for w in window_results]
        oos_pfs = [(w["oos_metrics"]["profit_factor"] or 0.0) for w in window_results]
        width = 0.35
        ax2.bar([i - width / 2 for i in x], is_pfs, width, label="IS PF")
        ax2.bar([i + width / 2 for i in x], oos_pfs, width, label="OOS PF")
        ax2.axhline(1.0, color="gray", linestyle="--", linewidth=1)
        ax2.set_title("IS vs OOS Profit Factor")
        ax2.set_xlabel("Window #")
        ax2.set_ylabel("Profit Factor")
        ax2.set_xticks(x)
        ax2.legend()
        ax2.grid(True, alpha=0.3, axis="y")
        fig2.tight_layout()
        fig2.savefig(out_dir / "is_vs_oos.png", dpi=120)
        plt.close(fig2)
        written.append("is_vs_oos.png")
    except ImportError:
        print("[warn] matplotlib not installed — skipping plots")

    return written


def _pf_str(pf, width=6):
    if pf is None:
        return f"{'inf':>{width}}"
    return f"{pf:>{width}.2f}"


def print_report(window_results: list[dict], combined: dict, stab: dict, out_dir: Path) -> None:
    print("=" * 78)
    print("Walk-Forward Results")
    print("=" * 78)
    print(f"{'#':>2}  {'IS Period':<25}  {'OOS Period':<25}  {'IS PF':>7}  {'OOS PF':>7}")
    for i, w in enumerate(window_results):
        print(
            f"{i+1:>2}  {w['is_period']:<25}  {w['oos_period']:<25}  "
            f"{_pf_str(w['is_metrics']['profit_factor'], 7)}  "
            f"{_pf_str(w['oos_metrics']['profit_factor'], 7)}"
        )
    print("-" * 78)
    print("Combined OOS:")
    print(f"  取引数        : {combined['num_trades']}")
    print(f"  勝率          : {combined['win_rate']:.2%}")
    print(f"  PF            : {combined['profit_factor']}")
    print(f"  最大DD        : {combined['max_drawdown']:.2%}")
    print(f"  シャープ      : {combined['sharpe']}")
    print(f"  期待値        : {combined['expected_value']}")
    print(f"  総リターン    : {combined['total_return']:.2%}")
    print("-" * 78)
    print("Stability:")
    print(f"  mean(IS PF)   : {stab['mean_is_pf']}")
    print(f"  mean(OOS PF)  : {stab['mean_oos_pf']}")
    print(f"  OOS PF stddev : {stab['oos_pf_stddev']}")
    print(f"  IS-OOS劣化率  : {stab['is_oos_degradation']:.2%}")
    print("-" * 78)
    print(f"判定: {'PASS' if stab['passed'] else 'OVERFIT'}")
    for msg in stab["fails"]:
        print(f"  [overfit] {msg}")
    for msg in stab["warns"]:
        print(f"  [warn] {msg}")
    print(f"出力先: {out_dir}")
    print("=" * 78)


def main() -> int:
    parser = argparse.ArgumentParser(description="Walk-forward validation runner")
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--tf", required=True)
    parser.add_argument("--period", required=True, help="ISO start:end of full period")
    parser.add_argument("--is-months", type=int, default=12)
    parser.add_argument("--oos-months", type=int, default=3)
    parser.add_argument("--step-months", type=int, default=3)
    parser.add_argument("--capital", type=float, default=10000.0)
    parser.add_argument("--fee", type=float, default=0.001)
    parser.add_argument("--slippage", type=float, default=0.0005)
    parser.add_argument("--out", default="results")
    args = parser.parse_args()

    strategy_path = Path(args.strategy).resolve()
    if not strategy_path.exists():
        print(f"[error] strategy not found: {strategy_path}", file=sys.stderr)
        return 2

    StrategyClass = load_strategy(strategy_path)
    strategy = StrategyClass(
        symbol=args.symbol, tf=args.tf, fee=args.fee, slippage=args.slippage
    )

    start, end = parse_period(args.period)
    windows = make_windows(
        start, end, args.is_months, args.oos_months, args.step_months
    )
    if not windows:
        print(
            f"[error] No windows fit in period {args.period} with "
            f"IS={args.is_months}m, OOS={args.oos_months}m, step={args.step_months}m",
            file=sys.stderr,
        )
        return 2

    print(f"[info] generated {len(windows)} window(s)")
    window_results = [run_window(strategy, w, args.capital) for w in windows]

    full_oos_start = window_results[0]["oos_period"].split(":")[0]
    full_oos_end = window_results[-1]["oos_period"].split(":")[1]
    full_oos_period = f"{full_oos_start}:{full_oos_end}"
    _, combined_eq, combined_metrics = combine_oos(
        window_results, args.capital, full_oos_period
    )

    stab = stability_and_overfit(window_results)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out) / f"{strategy_path.stem}_wf_{timestamp}"

    summary = {
        "strategy": strategy_path.stem,
        "symbol": args.symbol,
        "tf": args.tf,
        "period": args.period,
        "is_months": args.is_months,
        "oos_months": args.oos_months,
        "step_months": args.step_months,
        "capital": args.capital,
        "fee": args.fee,
        "slippage": args.slippage,
        "n_windows": len(windows),
        "windows": [
            {
                "is_period": w["is_period"],
                "oos_period": w["oos_period"],
                "params": w["params"],
                "is_metrics": w["is_metrics"],
                "oos_metrics": w["oos_metrics"],
            }
            for w in window_results
        ],
        "combined_oos_period": full_oos_period,
        "combined_oos": combined_metrics,
        "stability": stab,
        "passed": stab["passed"],
    }

    write_outputs(out_dir, summary, window_results, combined_eq)
    print_report(window_results, combined_metrics, stab, out_dir)
    return 0 if stab["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
