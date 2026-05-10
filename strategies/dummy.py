"""Dummy strategy for plumbing checks. Generates 150 random trades.

Not a real strategy — no data fetch, no signals. The PnL distribution is set
so that all SKILL.md pass criteria are satisfied for verification purposes.

Implements the walk-forward contract (`optimize` + `set_params`) too, while
remaining backwards compatible with the backtest skill: when `set_params` is
not called (i.e. `self.params` stays empty), `backtest` reproduces the
original seed=42 trade sequence exactly.
"""

from __future__ import annotations

import hashlib
import random
from datetime import datetime


class Strategy:
    def __init__(self, symbol: str, tf: str, fee: float, slippage: float) -> None:
        self.symbol = symbol
        self.tf = tf
        self.fee = fee
        self.slippage = slippage
        self.params: dict = {}

    def set_params(self, params: dict) -> None:
        self.params = dict(params or {})

    def optimize(self, is_period: str, capital: float) -> dict:
        # Pretend to optimize: deterministic per IS period.
        rng = random.Random(self._period_seed(is_period))
        return {
            "threshold": round(rng.uniform(0.0, 1.0), 4),
            "seed": rng.randint(0, 10 ** 6),
        }

    def backtest(self, period: str, capital: float) -> tuple[list[dict], list[float]]:
        # Backwards compat: with no params set, fall back to the original seed=42
        # so the backtest skill produces identical results to before.
        if self.params:
            base = int(self.params.get("seed", 42))
            seed = (base + self._period_seed(period)) & 0xFFFFFFFF
        else:
            seed = 42
        random.seed(seed)

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

    @staticmethod
    def _period_seed(period: str) -> int:
        return int(hashlib.md5(period.encode()).hexdigest(), 16) & 0xFFFFFFFF
