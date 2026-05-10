"""Walk-forward strategy template.

Beyond the backtest skill contract, walk-forward requires `optimize` and
`set_params`. The runner calls them in this order per window:

    params = strategy.optimize(is_period, capital)
    strategy.set_params(params)
    strategy.backtest(is_period,  capital)   # IS metrics
    strategy.backtest(oos_period, capital)   # OOS metrics

The same Strategy class can also be run by the backtest skill: in that case
`set_params` is never called, so `__init__` must give `self.params` a sensible
default and `backtest` must work with it.
"""

from __future__ import annotations


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
        # TODO: search parameters that maximize the IS objective.
        return {}

    def backtest(self, period: str, capital: float) -> tuple[list[dict], list[float]]:
        # TODO: simulate trades, optionally using self.params.
        trades: list[dict] = []
        equity: list[float] = [capital]
        return trades, equity
