"""Dummy strategy for plumbing checks. Generates 150 random trades.

Not a real strategy — no data fetch, no signals. The PnL distribution is set
so that all SKILL.md pass criteria are satisfied for verification purposes.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta


class Strategy:
    def __init__(self, symbol: str, tf: str, fee: float, slippage: float) -> None:
        self.symbol = symbol
        self.tf = tf
        self.fee = fee
        self.slippage = slippage

    def backtest(self, period: str, capital: float) -> tuple[list[dict], list[float]]:
        random.seed(42)

        start_str, end_str = period.split(":")
        start = datetime.fromisoformat(start_str)
        end = datetime.fromisoformat(end_str)

        n_trades = 150
        step = (end - start) / n_trades

        trades: list[dict] = []
        equity: list[float] = [capital]
        balance = capital

        for i in range(n_trades):
            entry_time = start + step * i
            exit_time = start + step * (i + 0.5)
            side = random.choice(["long", "short"])
            entry_price = 30000 + random.uniform(-1000, 1000)
            pnl = random.gauss(50, 200)
            exit_price = entry_price + (pnl if side == "long" else -pnl)
            balance += pnl
            trades.append({
                "entry_time": entry_time.isoformat(),
                "exit_time": exit_time.isoformat(),
                "side": side,
                "entry_price": round(entry_price, 2),
                "exit_price": round(exit_price, 2),
                "pnl": round(pnl, 2),
            })
            equity.append(round(balance, 2))

        return trades, equity
