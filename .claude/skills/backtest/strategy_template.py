"""Strategy template — copy this file into `strategies/<name>.py` and fill in.

Contract (see SKILL.md):
    class Strategy:
        def __init__(self, symbol: str, tf: str, fee: float, slippage: float): ...
        def backtest(self, period: str, capital: float) -> tuple[list, list]:
            # Returns (trades, equity).
            # trades: list of dicts with keys
            #   entry_time, exit_time, side ("long"|"short"),
            #   entry_price, exit_price, pnl
            # equity: list of floats starting with `capital`, ending with final equity.
            ...

Run with:
    python .claude/skills/backtest/run_backtest.py \
      --strategy strategies/<name>.py \
      --symbol BTC/USDT --tf 1h \
      --period 2023-01-01:2025-01-01
"""

from __future__ import annotations


class Strategy:
    def __init__(self, symbol: str, tf: str, fee: float, slippage: float) -> None:
        self.symbol = symbol
        self.tf = tf
        self.fee = fee
        self.slippage = slippage

    def backtest(self, period: str, capital: float) -> tuple[list[dict], list[float]]:
        # TODO: load data, generate signals, simulate trades.
        trades: list[dict] = []
        equity: list[float] = [capital]
        return trades, equity
