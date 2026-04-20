"""Walk-forward parameter selection for the BS edge strategy.

The strategy has two main hyperparameters: the sigma lookback window and
the sigma estimator. To avoid overfitting we pick them on rolling train
windows and evaluate the next ``test_days`` out-of-sample, then step
forward. The final report stacks all OOS trades.

We deliberately keep the parameter surface small. Edge thresholds and
stake rules are held fixed within a run; vary them across runs instead.
"""

from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from .backtest import BacktestResult, backtest_many
from .config import Config
from .market_loader import UpDownMarket
from .metrics import summarise

logger = logging.getLogger(__name__)


@dataclass
class Fold:
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    best_window_min: int
    best_estimator: str
    train_metric: float
    trades: pd.DataFrame


@dataclass
class WalkForwardReport:
    folds: list[Fold] = field(default_factory=list)

    @property
    def all_trades(self) -> pd.DataFrame:
        if not self.folds:
            return pd.DataFrame()
        return pd.concat([f.trades for f in self.folds], ignore_index=True)


def walk_forward(
    markets: list[UpDownMarket],
    btc_bars: pd.DataFrame,
    price_histories: dict[str, pd.DataFrame],
    cfg: Config,
    *,
    train_days: int | None = None,
    test_days: int | None = None,
    selection_metric: str = "sharpe",
) -> WalkForwardReport:
    """Run walk-forward over the whole market universe.

    ``selection_metric`` is one of the attributes on ``Summary``. We
    maximise it on the training fold to pick (window, estimator) and
    then apply that pair on the test fold.
    """
    train_days = train_days if train_days is not None else cfg.train_days
    test_days = test_days if test_days is not None else cfg.test_days
    if not markets:
        return WalkForwardReport()

    markets_sorted = sorted(markets, key=lambda m: m.close_ts)
    first_ts = markets_sorted[0].open_ts
    last_ts = markets_sorted[-1].close_ts
    logger.info(
        "walk-forward over %d markets spanning %s -> %s",
        len(markets_sorted),
        datetime.fromtimestamp(first_ts, tz=timezone.utc).isoformat(),
        datetime.fromtimestamp(last_ts, tz=timezone.utc).isoformat(),
    )

    report = WalkForwardReport()
    step = int(timedelta(days=test_days).total_seconds())
    train_span = int(timedelta(days=train_days).total_seconds())

    cursor = first_ts + train_span
    while cursor < last_ts:
        train_start = cursor - train_span
        train_end = cursor
        test_start = cursor
        test_end = min(cursor + step, last_ts)

        train_markets = [m for m in markets_sorted if train_start <= m.close_ts < train_end]
        test_markets = [m for m in markets_sorted if test_start <= m.close_ts < test_end]

        if not train_markets or not test_markets:
            cursor += step
            continue

        best = _select_params(
            train_markets, btc_bars, price_histories, cfg, selection_metric
        )
        if best is None:
            cursor += step
            continue
        best_window, best_estimator, train_metric = best

        test_result = backtest_many(
            test_markets,
            btc_bars,
            price_histories,
            cfg,
            sigma_window_min=best_window,
            sigma_estimator=best_estimator,
        )
        report.folds.append(
            Fold(
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                best_window_min=best_window,
                best_estimator=best_estimator,
                train_metric=train_metric,
                trades=test_result.to_frame(),
            )
        )
        logger.info(
            "fold %s -> %s: window=%d estimator=%s train_%s=%.3f trades=%d",
            datetime.fromtimestamp(test_start, tz=timezone.utc).date(),
            datetime.fromtimestamp(test_end, tz=timezone.utc).date(),
            best_window,
            best_estimator,
            selection_metric,
            train_metric,
            len(test_result.trades),
        )
        cursor += step
    return report


def _select_params(
    train_markets: list[UpDownMarket],
    btc_bars: pd.DataFrame,
    price_histories: dict[str, pd.DataFrame],
    cfg: Config,
    selection_metric: str,
) -> tuple[int, str, float] | None:
    best: tuple[int, str, float] | None = None
    for window, est in itertools.product(cfg.sigma_windows_min, cfg.sigma_estimators):
        try:
            res: BacktestResult = backtest_many(
                train_markets,
                btc_bars,
                price_histories,
                cfg,
                sigma_window_min=window,
                sigma_estimator=est,
            )
        except Exception as exc:
            logger.warning("train failed for %s/%s: %s", window, est, exc)
            continue
        if not res.trades:
            continue
        summary = summarise(res.to_frame())
        metric = getattr(summary, selection_metric, None)
        if metric is None or np.isnan(metric):
            continue
        if best is None or metric > best[2]:
            best = (window, est, float(metric))
    return best
