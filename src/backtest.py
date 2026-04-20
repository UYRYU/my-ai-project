"""Estimate realistic monthly PnL from a trades.jsonl log.

Replays `opportunity` events and applies realistic fill assumptions:
- X% partial fill rate (each failure loses ~2% of basket size)
- Y% slippage tax (cross-spread cost)
- Z% of opportunities we race-lose to competitors

Usage:
    python -m src.backtest trades.jsonl --bankroll 500 --position 50
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def run(
    path: Path,
    *,
    bankroll: float,
    position_usd: float,
    partial_fill_rate: float,
    race_loss_rate: float,
    slippage_tax: float,
) -> None:
    opportunities = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("event") == "opportunity":
                opportunities.append(row)

    if not opportunities:
        print(f"{path}: no opportunity events found")
        return

    total_edge = 0.0
    total_slippage = 0.0
    total_unwind_cost = 0.0
    total_race_lost = 0
    executed = 0

    for opp in opportunities:
        edge_pct = float(opp.get("edge", 0))
        edge_usd = position_usd * edge_pct

        # Some fraction of detected opportunities will be raced away
        if _bernoulli(race_loss_rate):
            total_race_lost += 1
            continue

        # Some fraction partial-fill and need unwinding
        if _bernoulli(partial_fill_rate):
            total_unwind_cost += position_usd * 0.02
            continue

        total_edge += edge_usd
        total_slippage += position_usd * slippage_tax
        executed += 1

    net_pnl = total_edge - total_slippage - total_unwind_cost
    raw_rate = net_pnl / bankroll if bankroll > 0 else 0.0

    print(f"== Backtest: {path} ==")
    print(f"Opportunities detected: {len(opportunities)}")
    print(f"  raced away (lost):    {total_race_lost}")
    print(f"  partial filled:       ~{int(partial_fill_rate * len(opportunities))}")
    print(f"  executed:             {executed}")
    print(f"")
    print(f"Gross edge:              ${total_edge:.2f}")
    print(f"Slippage:               -${total_slippage:.2f}")
    print(f"Unwind cost:            -${total_unwind_cost:.2f}")
    print(f"Net PnL:                 ${net_pnl:.2f}")
    print(f"Return on bankroll:       {raw_rate * 100:.2f}%")
    print(f"")
    # Project to monthly if the log covers enough time
    ts_values = [float(o.get("ts", 0)) for o in opportunities if o.get("ts")]
    if len(ts_values) >= 2:
        days = (max(ts_values) - min(ts_values)) / 86400
        if days < 0.5:
            print(f"Log span: {days * 24:.2f} hours (too short for monthly projection)")
            print(f"  Per-basket economics: ${net_pnl / max(executed, 1):.3f} net / basket")
            print(f"  Run the bot for 1+ day to get a meaningful monthly estimate.")
        else:
            daily_pnl = net_pnl / days
            monthly_pnl = daily_pnl * 30
            monthly_pct = monthly_pnl / bankroll * 100 if bankroll > 0 else 0
            print(f"Log span: {days:.2f} days")
            print(f"Projected daily PnL:   ${daily_pnl:.2f}")
            print(f"Projected monthly PnL: ${monthly_pnl:.2f} ({monthly_pct:.1f}% of bankroll)")


def _bernoulli(p: float) -> bool:
    import random
    return random.random() < p


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("path", nargs="?", default="trades.jsonl")
    p.add_argument("--bankroll", type=float, default=500.0)
    p.add_argument("--position", type=float, default=50.0)
    p.add_argument("--partial-fill-rate", type=float, default=0.05)
    p.add_argument("--race-loss-rate", type=float, default=0.40,
                   help="fraction of detected arbs lost to faster bots (0.4 = REST polling, 0.1 = WS)")
    p.add_argument("--slippage-tax", type=float, default=0.003)
    args = p.parse_args()

    path = Path(args.path)
    if not path.exists():
        print(f"{path} not found")
        return 1
    run(
        path,
        bankroll=args.bankroll,
        position_usd=args.position,
        partial_fill_rate=args.partial_fill_rate,
        race_loss_rate=args.race_loss_rate,
        slippage_tax=args.slippage_tax,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
