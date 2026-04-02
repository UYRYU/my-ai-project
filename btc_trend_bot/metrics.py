"""Performance metrics calculator for BTC Trend Long Bot.

All functions operate on a trade log DataFrame and/or equity curve Series.

Expected trades DataFrame columns:
    entry_time, exit_time, entry_price, exit_price, pnl, pnl_pct,
    direction, strategy, stop_loss, take_profit, exit_reason

Equity Series: indexed by datetime, values are portfolio value.
"""

from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger


# ---------------------------------------------------------------------------
# Individual metric functions
# ---------------------------------------------------------------------------

def calc_total_profit(trades: pd.DataFrame) -> float:
    """Return the sum of all trade PnL."""
    if trades.empty:
        return 0.0
    return float(trades["pnl"].sum())


def calc_profit_factor(trades: pd.DataFrame) -> float:
    """sum(wins) / abs(sum(losses)).  Returns inf when no losses."""
    if trades.empty:
        return 0.0
    wins = trades.loc[trades["pnl"] > 0, "pnl"].sum()
    losses = trades.loc[trades["pnl"] < 0, "pnl"].sum()
    if losses == 0:
        return float("inf") if wins > 0 else 0.0
    return float(wins / abs(losses))


def calc_expectancy(trades: pd.DataFrame) -> float:
    """Average profit per trade."""
    if trades.empty:
        return 0.0
    return float(trades["pnl"].mean())


def calc_max_drawdown(equity: pd.Series) -> tuple[float, float]:
    """Return (max_drawdown_absolute, max_drawdown_pct).

    Drawdown is measured from the running peak to the subsequent trough.
    """
    if equity.empty:
        return 0.0, 0.0

    running_max = equity.cummax()
    drawdown_abs = running_max - equity
    drawdown_pct = drawdown_abs / running_max

    # Replace any NaN / inf from division (e.g. running_max == 0)
    drawdown_pct = drawdown_pct.replace([np.inf, -np.inf], 0.0).fillna(0.0)

    max_dd_abs = float(drawdown_abs.max())
    max_dd_pct = float(drawdown_pct.max())
    return max_dd_abs, max_dd_pct


def calc_calmar_ratio(trades: pd.DataFrame, equity: pd.Series) -> float:
    """Annual return / max drawdown (percentage).

    Annual return is computed from the equity curve start/end values
    annualised to 365 days.
    """
    if equity.empty or len(equity) < 2:
        return 0.0

    _, max_dd_pct = calc_max_drawdown(equity)
    if max_dd_pct == 0:
        return float("inf") if equity.iloc[-1] > equity.iloc[0] else 0.0

    total_return = (equity.iloc[-1] / equity.iloc[0]) - 1.0

    # Duration in years
    duration = (equity.index[-1] - equity.index[0]).total_seconds() / (365.25 * 86400)
    if duration <= 0:
        return 0.0

    annual_return = (1 + total_return) ** (1 / duration) - 1.0
    return float(annual_return / max_dd_pct)


def calc_win_rate(trades: pd.DataFrame) -> float:
    """Fraction of trades with positive PnL (0.0 – 1.0)."""
    if trades.empty:
        return 0.0
    return float((trades["pnl"] > 0).sum() / len(trades))


def calc_avg_win_loss_ratio(trades: pd.DataFrame) -> float:
    """avg_win / avg_loss (absolute).  Returns inf when no losses."""
    if trades.empty:
        return 0.0
    wins = trades.loc[trades["pnl"] > 0, "pnl"]
    losses = trades.loc[trades["pnl"] < 0, "pnl"]
    if losses.empty:
        return float("inf") if not wins.empty else 0.0
    if wins.empty:
        return 0.0
    avg_win = wins.mean()
    avg_loss = abs(losses.mean())
    if avg_loss == 0:
        return float("inf")
    return float(avg_win / avg_loss)


def calc_avg_holding_time(trades: pd.DataFrame) -> float:
    """Average holding time in hours."""
    if trades.empty:
        return 0.0
    durations = pd.to_datetime(trades["exit_time"]) - pd.to_datetime(trades["entry_time"])
    avg_seconds = durations.dt.total_seconds().mean()
    return float(avg_seconds / 3600.0)


def calc_high_tp_rate(trades: pd.DataFrame, threshold_rr: float = 3.0) -> float:
    """Percentage of trades that achieved a reward-to-risk ratio > threshold.

    RR is calculated as pnl / abs(entry_price - stop_loss) per unit.
    Trades without a valid stop_loss are excluded from the denominator.
    """
    if trades.empty:
        return 0.0

    risk = (trades["entry_price"] - trades["stop_loss"]).abs()
    valid = risk > 0
    if valid.sum() == 0:
        return 0.0

    rr = trades.loc[valid, "pnl_pct"] / (risk[valid] / trades.loc[valid, "entry_price"] * 100)
    high_rr_count = (rr > threshold_rr).sum()
    return float(high_rr_count / valid.sum())


# ---------------------------------------------------------------------------
# Aggregate helpers
# ---------------------------------------------------------------------------

def calc_all_metrics(trades: pd.DataFrame, equity: pd.Series) -> dict:
    """Compute every metric and return as a single dictionary."""
    max_dd_abs, max_dd_pct = calc_max_drawdown(equity)

    metrics = {
        "total_profit": calc_total_profit(trades),
        "profit_factor": calc_profit_factor(trades),
        "expectancy": calc_expectancy(trades),
        "max_drawdown_abs": max_dd_abs,
        "max_drawdown_pct": max_dd_pct,
        "calmar_ratio": calc_calmar_ratio(trades, equity),
        "win_rate": calc_win_rate(trades),
        "avg_win_loss_ratio": calc_avg_win_loss_ratio(trades),
        "avg_holding_time_hours": calc_avg_holding_time(trades),
        "high_tp_rate_3rr": calc_high_tp_rate(trades, threshold_rr=3.0),
        "total_trades": len(trades),
        "winning_trades": int((trades["pnl"] > 0).sum()) if not trades.empty else 0,
        "losing_trades": int((trades["pnl"] < 0).sum()) if not trades.empty else 0,
    }

    logger.debug("Calculated all metrics: {} trades, profit={:.2f}, win_rate={:.2%}",
                 metrics["total_trades"], metrics["total_profit"], metrics["win_rate"])
    return metrics


def calc_regime_metrics(
    trades: pd.DataFrame,
    equity: pd.Series,
    regime_labels: pd.Series,
) -> dict:
    """Compute metrics split by market regime (bull / bear / sideways).

    Parameters
    ----------
    trades : pd.DataFrame
        Trade log with ``entry_time`` column.
    equity : pd.Series
        Equity curve indexed by datetime.
    regime_labels : pd.Series
        Series indexed by datetime with values in {"bull", "bear", "sideways"}.
        Each trade is assigned to the regime active at its ``entry_time``.

    Returns
    -------
    dict
        ``{regime_name: metrics_dict, ...}``
    """
    if trades.empty:
        return {}

    regime_labels = regime_labels.sort_index()

    # Map each trade to the regime at entry_time using forward-fill lookup
    entry_times = pd.to_datetime(trades["entry_time"])
    trade_regimes = regime_labels.reindex(
        regime_labels.index.union(entry_times)
    ).ffill().reindex(entry_times)

    result: dict = {}
    for regime in trade_regimes.unique():
        if pd.isna(regime):
            continue
        mask = trade_regimes.values == regime
        regime_trades = trades.loc[mask].copy()
        if regime_trades.empty:
            continue

        # Build a regime-specific equity curve from matching trade PnLs
        regime_equity = _build_equity_from_trades(regime_trades, equity.iloc[0])
        result[str(regime)] = calc_all_metrics(regime_trades, regime_equity)
        logger.info("Regime '{}': {} trades, profit={:.2f}",
                     regime, len(regime_trades), result[str(regime)]["total_profit"])

    return result


# ---------------------------------------------------------------------------
# Top-trade analysis
# ---------------------------------------------------------------------------

def get_top_trades(
    trades: pd.DataFrame,
    n: int = 10,
    best: bool = True,
) -> pd.DataFrame:
    """Return the top *n* winning (best=True) or losing (best=False) trades."""
    if trades.empty:
        return trades
    ascending = not best
    sorted_trades = trades.sort_values("pnl", ascending=ascending)
    return sorted_trades.head(n).copy()


def analyze_top_trades(trades: pd.DataFrame, n: int = 10) -> dict:
    """Identify common features among top wins and top losses.

    Returns
    -------
    dict
        ``{"top_wins": {...}, "top_losses": {...}}`` with summary stats for
        each group: avg_pnl, avg_holding_hours, most_common_strategy,
        most_common_exit_reason, avg_entry_price.
    """
    if trades.empty:
        return {"top_wins": {}, "top_losses": {}}

    top_wins = get_top_trades(trades, n=n, best=True)
    top_losses = get_top_trades(trades, n=n, best=False)

    def _summarise(group: pd.DataFrame) -> dict:
        if group.empty:
            return {}
        durations = (
            pd.to_datetime(group["exit_time"]) - pd.to_datetime(group["entry_time"])
        ).dt.total_seconds() / 3600.0

        summary: dict = {
            "count": len(group),
            "avg_pnl": float(group["pnl"].mean()),
            "avg_pnl_pct": float(group["pnl_pct"].mean()),
            "avg_holding_hours": float(durations.mean()),
            "avg_entry_price": float(group["entry_price"].mean()),
        }

        if "strategy" in group.columns and not group["strategy"].isna().all():
            summary["most_common_strategy"] = str(group["strategy"].mode().iloc[0])
        if "exit_reason" in group.columns and not group["exit_reason"].isna().all():
            summary["most_common_exit_reason"] = str(group["exit_reason"].mode().iloc[0])

        return summary

    result = {
        "top_wins": _summarise(top_wins),
        "top_losses": _summarise(top_losses),
    }

    logger.info(
        "Top-trade analysis: best avg PnL={:.2f}, worst avg PnL={:.2f}",
        result["top_wins"].get("avg_pnl", 0),
        result["top_losses"].get("avg_pnl", 0),
    )
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_equity_from_trades(
    trades: pd.DataFrame,
    initial_capital: float,
) -> pd.Series:
    """Reconstruct a simple equity curve from trade PnLs.

    Returns a Series indexed by ``exit_time`` with cumulative equity.
    """
    sorted_trades = trades.sort_values("exit_time")
    cumulative_pnl = sorted_trades["pnl"].cumsum() + initial_capital
    equity = pd.Series(
        cumulative_pnl.values,
        index=pd.to_datetime(sorted_trades["exit_time"]).values,
    )
    # Prepend initial capital at the first entry_time
    first_entry = pd.to_datetime(sorted_trades["entry_time"].iloc[0])
    equity.loc[first_entry] = initial_capital
    equity = equity.sort_index()
    return equity
