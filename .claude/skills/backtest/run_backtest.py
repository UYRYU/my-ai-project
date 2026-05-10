"""Standard backtest runner for all strategies.

Loads a Strategy class from a given file, runs `backtest()`, computes the
required metrics, applies the pass/fail rules from SKILL.md, and writes
metrics.json / trades.csv / equity_curve.png to results/<name>_<timestamp>/.

Exit code: 0 if all pass criteria are met, 1 otherwise.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import sys
from datetime import datetime
from pathlib import Path


PASS_CRITERIA = {
    "num_trades_min": 100,
    "win_rate_min": 0.40,
    "profit_factor_min": 1.30,
    "max_drawdown_max": 0.30,
    "sharpe_min": 1.0,
    "expected_value_min": 0.0,
}

OVERFIT_HINTS = {
    "profit_factor_max": 3.0,
    "win_rate_max": 0.70,
}


def load_strategy(strategy_path: Path):
    spec = importlib.util.spec_from_file_location("user_strategy", strategy_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load strategy from {strategy_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "Strategy"):
        raise AttributeError(f"{strategy_path} does not define a `Strategy` class")
    return module.Strategy


def parse_period(period: str) -> tuple[datetime, datetime]:
    start_str, end_str = period.split(":")
    return datetime.fromisoformat(start_str), datetime.fromisoformat(end_str)


def compute_metrics(trades: list[dict], equity: list[float], period: str) -> dict:
    num_trades = len(trades)
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    win_rate = len(wins) / num_trades if num_trades else 0.0
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")
    expected_value = sum(pnls) / num_trades if num_trades else 0.0
    total_return = (equity[-1] / equity[0] - 1.0) if equity and equity[0] else 0.0

    peak = equity[0] if equity else 0.0
    max_dd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak
            if dd > max_dd:
                max_dd = dd

    # Sharpe on trade-level returns, annualized by trades-per-year.
    start, end = parse_period(period)
    duration_years = max((end - start).days / 365.25, 1e-9)
    trades_per_year = num_trades / duration_years

    if num_trades > 1:
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
        "num_trades": num_trades,
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else None,
        "max_drawdown": round(max_dd, 4),
        "sharpe": round(sharpe, 4),
        "expected_value": round(expected_value, 4),
        "total_return": round(total_return, 4),
        "gross_profit": round(gross_profit, 4),
        "gross_loss": round(gross_loss, 4),
        "final_equity": round(equity[-1], 4) if equity else 0.0,
    }


def evaluate(metrics: dict) -> tuple[bool, list[str], list[str]]:
    fails: list[str] = []
    warns: list[str] = []

    if metrics["num_trades"] < PASS_CRITERIA["num_trades_min"]:
        fails.append(f"取引数 {metrics['num_trades']} < {PASS_CRITERIA['num_trades_min']} (失格)")
    if metrics["win_rate"] < PASS_CRITERIA["win_rate_min"]:
        fails.append(f"勝率 {metrics['win_rate']:.2%} < {PASS_CRITERIA['win_rate_min']:.0%}")
    pf = metrics["profit_factor"]
    if pf is None or pf >= PASS_CRITERIA["profit_factor_min"]:
        pass
    else:
        fails.append(f"PF {pf} < {PASS_CRITERIA['profit_factor_min']}")
    if metrics["max_drawdown"] > PASS_CRITERIA["max_drawdown_max"]:
        fails.append(f"最大DD {metrics['max_drawdown']:.2%} > {PASS_CRITERIA['max_drawdown_max']:.0%}")
    if metrics["sharpe"] < PASS_CRITERIA["sharpe_min"]:
        fails.append(f"シャープ {metrics['sharpe']} < {PASS_CRITERIA['sharpe_min']}")
    if metrics["expected_value"] <= PASS_CRITERIA["expected_value_min"]:
        fails.append(f"期待値 {metrics['expected_value']} <= {PASS_CRITERIA['expected_value_min']}")

    if pf is not None and pf > OVERFIT_HINTS["profit_factor_max"]:
        warns.append(f"PF {pf} > {OVERFIT_HINTS['profit_factor_max']} (過学習を疑う)")
    if metrics["win_rate"] > OVERFIT_HINTS["win_rate_max"]:
        warns.append(f"勝率 {metrics['win_rate']:.2%} > {OVERFIT_HINTS['win_rate_max']:.0%} (過学習を疑う)")

    return len(fails) == 0, fails, warns


def write_outputs(out_dir: Path, metrics: dict, trades: list[dict], equity: list[float]) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    metrics_path = out_dir / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False))
    written.append(metrics_path.name)

    trades_path = out_dir / "trades.csv"
    fieldnames = ["entry_time", "exit_time", "side", "entry_price", "exit_price", "pnl"]
    with trades_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for t in trades:
            writer.writerow({k: t.get(k, "") for k in fieldnames})
    written.append(trades_path.name)

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(range(len(equity)), equity, linewidth=1.2)
        ax.set_title("Equity Curve")
        ax.set_xlabel("Trade #")
        ax.set_ylabel("Equity")
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        plot_path = out_dir / "equity_curve.png"
        fig.savefig(plot_path, dpi=120)
        plt.close(fig)
        written.append(plot_path.name)
    except ImportError:
        print("[warn] matplotlib not installed — skipping equity_curve.png")

    return written


def print_report(metrics: dict, passed: bool, fails: list[str], warns: list[str], out_dir: Path) -> None:
    print("=" * 60)
    print("Backtest Metrics")
    print("=" * 60)
    print(f"  取引数        : {metrics['num_trades']}")
    print(f"  勝率          : {metrics['win_rate']:.2%}")
    pf = metrics["profit_factor"]
    print(f"  PF            : {pf if pf is not None else 'inf'}")
    print(f"  最大DD        : {metrics['max_drawdown']:.2%}")
    print(f"  シャープ      : {metrics['sharpe']}")
    print(f"  期待値        : {metrics['expected_value']}")
    print(f"  総リターン    : {metrics['total_return']:.2%}")
    print(f"  最終資金      : {metrics['final_equity']}")
    print("-" * 60)
    print(f"判定: {'PASS' if passed else 'FAIL'}")
    for msg in fails:
        print(f"  [fail] {msg}")
    for msg in warns:
        print(f"  [warn] {msg}")
    print(f"出力先: {out_dir}")
    print("=" * 60)


def main() -> int:
    parser = argparse.ArgumentParser(description="Standard backtest runner")
    parser.add_argument("--strategy", required=True, help="Path to strategy .py file")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--tf", required=True, help="Timeframe, e.g. 1h")
    parser.add_argument("--period", required=True, help="ISO range start:end")
    parser.add_argument("--capital", type=float, default=10000.0)
    parser.add_argument("--fee", type=float, default=0.001)
    parser.add_argument("--slippage", type=float, default=0.0005)
    parser.add_argument("--results-dir", default="results")
    args = parser.parse_args()

    strategy_path = Path(args.strategy).resolve()
    if not strategy_path.exists():
        print(f"[error] strategy file not found: {strategy_path}", file=sys.stderr)
        return 2

    StrategyClass = load_strategy(strategy_path)
    strategy = StrategyClass(symbol=args.symbol, tf=args.tf, fee=args.fee, slippage=args.slippage)
    trades, equity = strategy.backtest(period=args.period, capital=args.capital)

    metrics = compute_metrics(trades, equity, args.period)
    passed, fails, warns = evaluate(metrics)

    metrics_full = {
        "strategy": strategy_path.stem,
        "symbol": args.symbol,
        "tf": args.tf,
        "period": args.period,
        "capital": args.capital,
        "fee": args.fee,
        "slippage": args.slippage,
        "passed": passed,
        "fails": fails,
        "warns": warns,
        **metrics,
    }

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.results_dir) / f"{strategy_path.stem}_{timestamp}"
    write_outputs(out_dir, metrics_full, trades, equity)
    print_report(metrics_full, passed, fails, warns, out_dir)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
