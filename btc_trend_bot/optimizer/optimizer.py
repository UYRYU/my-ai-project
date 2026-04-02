"""Optuna-based parameter optimizer for BTC Trend Long Bot strategies.

Provides train/validation/test splitting, walk-forward optimization,
and multi-strategy comparison.
"""

from __future__ import annotations

from typing import Any, Type

import optuna
import pandas as pd
from loguru import logger

from btc_trend_bot.backtest.engine import BacktestEngine
from btc_trend_bot.backtest.exit_manager import ExitManager
from btc_trend_bot.feature_engineering import FeatureEngineer
from btc_trend_bot.metrics import calc_all_metrics
from btc_trend_bot.strategies.base_strategy import BaseStrategy


# Silence Optuna's own INFO logs so they don't flood the console
optuna.logging.set_verbosity(optuna.logging.WARNING)


class StrategyOptimizer:
    """Optuna-powered parameter optimizer for :class:`BaseStrategy` subclasses."""

    def __init__(self, config: dict) -> None:
        """Initialise from the ``optimization`` section of settings.yaml.

        Parameters
        ----------
        config : dict
            Keys: n_trials, train_ratio, validation_ratio, test_ratio, objective.
        """
        self.n_trials: int = config.get("n_trials", 200)
        self.train_ratio: float = config.get("train_ratio", 0.6)
        self.validation_ratio: float = config.get("validation_ratio", 0.2)
        self.test_ratio: float = config.get("test_ratio", 0.2)
        self.objective_metric: str = config.get("objective", "calmar_ratio")

        logger.info(
            "StrategyOptimizer initialised: n_trials={}, split={}/{}/{}, objective={}",
            self.n_trials,
            self.train_ratio,
            self.validation_ratio,
            self.test_ratio,
            self.objective_metric,
        )

    # ------------------------------------------------------------------
    # Data splitting
    # ------------------------------------------------------------------

    def split_data(
        self, df: pd.DataFrame
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """Split *df* into train / validation / test sets by time order.

        Returns
        -------
        tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]
            (train, validation, test) DataFrames.
        """
        n = len(df)
        train_end = int(n * self.train_ratio)
        val_end = train_end + int(n * self.validation_ratio)

        train = df.iloc[:train_end].copy()
        validation = df.iloc[train_end:val_end].copy()
        test = df.iloc[val_end:].copy()

        logger.info(
            "Data split: train={} rows, validation={} rows, test={} rows",
            len(train),
            len(validation),
            len(test),
        )
        return train, validation, test

    # ------------------------------------------------------------------
    # Core optimisation
    # ------------------------------------------------------------------

    def optimize(
        self,
        strategy_class: Type[BaseStrategy],
        df: pd.DataFrame,
        exit_config: dict,
        backtest_config: dict,
    ) -> dict:
        """Run Optuna optimisation and return the best parameters.

        Steps
        -----
        1. Split data into train / validation / test.
        2. Create an Optuna study (maximise the objective metric).
        3. For each trial, sample parameters from
           ``strategy_class.get_param_space()``.
        4. Run a backtest on the **train** set.
        5. Evaluate on the **validation** set.
        6. Return the best parameters together with train, validation, and
           test metrics.

        Parameters
        ----------
        strategy_class : Type[BaseStrategy]
            Strategy class (not instance) to optimise.
        df : pd.DataFrame
            OHLCV DataFrame with features already added.
        exit_config : dict
            Exit-manager configuration forwarded to :class:`ExitManager`.
        backtest_config : dict
            Backtest engine configuration forwarded to :class:`BacktestEngine`.

        Returns
        -------
        dict
            ``best_params``, ``train_metrics``, ``validation_metrics``,
            ``test_metrics``, ``n_trials``, ``best_trial_number``.
        """
        train_df, val_df, test_df = self.split_data(df)

        # Retrieve parameter space from a temporary instance
        temp_strategy = strategy_class()
        param_space: dict = temp_strategy.get_param_space()

        if not param_space:
            logger.warning(
                "Strategy {} returned empty param_space; skipping optimisation",
                strategy_class.__name__,
            )
            return self._evaluate_default(
                strategy_class, train_df, val_df, test_df, exit_config, backtest_config
            )

        study = optuna.create_study(
            direction="maximize",
            study_name=f"optimize_{strategy_class.__name__}",
        )

        def objective(trial: optuna.Trial) -> float:
            params = self._sample_params(trial, param_space)
            metrics = self._run_backtest(
                strategy_class, params, train_df, exit_config, backtest_config
            )
            value = metrics.get(self.objective_metric, 0.0)
            # Handle inf / nan so Optuna doesn't choke
            if not pd.notna(value) or value == float("inf"):
                return 0.0
            return float(value)

        study.optimize(objective, n_trials=self.n_trials, show_progress_bar=False)

        best_params = study.best_trial.params
        logger.info(
            "Optimisation complete for {}: best {} = {:.4f} (trial #{})",
            strategy_class.__name__,
            self.objective_metric,
            study.best_value,
            study.best_trial.number,
        )

        # Evaluate best params on all splits
        train_metrics = self._run_backtest(
            strategy_class, best_params, train_df, exit_config, backtest_config
        )
        val_metrics = self._run_backtest(
            strategy_class, best_params, val_df, exit_config, backtest_config
        )
        test_metrics = self._run_backtest(
            strategy_class, best_params, test_df, exit_config, backtest_config
        )

        return {
            "strategy_name": strategy_class.__name__,
            "best_params": best_params,
            "train_metrics": train_metrics,
            "validation_metrics": val_metrics,
            "test_metrics": test_metrics,
            "n_trials": self.n_trials,
            "best_trial_number": study.best_trial.number,
        }

    # ------------------------------------------------------------------
    # Walk-forward optimisation
    # ------------------------------------------------------------------

    def walk_forward(
        self,
        strategy_class: Type[BaseStrategy],
        df: pd.DataFrame,
        exit_config: dict,
        backtest_config: dict,
        n_splits: int = 5,
        train_pct: int = 70,
    ) -> list[dict]:
        """Walk-forward optimisation over *n_splits* expanding windows.

        For each split window the first *train_pct*% of the data is used
        for optimisation and the remainder for out-of-sample testing.

        Parameters
        ----------
        strategy_class : Type[BaseStrategy]
            Strategy class to optimise.
        df : pd.DataFrame
            Full OHLCV DataFrame with features.
        exit_config : dict
            Exit-manager configuration.
        backtest_config : dict
            Backtest engine configuration.
        n_splits : int
            Number of walk-forward windows.
        train_pct : int
            Percentage of each window used for training (0-100).

        Returns
        -------
        list[dict]
            Per-split results, each containing ``split_index``,
            ``train_start``, ``train_end``, ``test_start``, ``test_end``,
            ``best_params``, ``train_metrics``, ``test_metrics``.
        """
        n = len(df)
        window_size = n // n_splits
        results: list[dict] = []

        logger.info(
            "Walk-forward: {} splits, window_size={}, train_pct={}%",
            n_splits,
            window_size,
            train_pct,
        )

        temp_strategy = strategy_class()
        param_space: dict = temp_strategy.get_param_space()

        for split_idx in range(n_splits):
            start = split_idx * window_size
            end = start + window_size if split_idx < n_splits - 1 else n
            window = df.iloc[start:end]

            train_end_idx = int(len(window) * train_pct / 100)
            train_data = window.iloc[:train_end_idx].copy()
            test_data = window.iloc[train_end_idx:].copy()

            if train_data.empty or test_data.empty:
                logger.warning("Split {} has empty train or test set; skipping", split_idx)
                continue

            # Optimise on train portion
            if param_space:
                study = optuna.create_study(
                    direction="maximize",
                    study_name=f"wf_{strategy_class.__name__}_split{split_idx}",
                )

                def _make_objective(td: pd.DataFrame) -> Any:
                    def objective(trial: optuna.Trial) -> float:
                        params = self._sample_params(trial, param_space)
                        metrics = self._run_backtest(
                            strategy_class, params, td, exit_config, backtest_config
                        )
                        value = metrics.get(self.objective_metric, 0.0)
                        if not pd.notna(value) or value == float("inf"):
                            return 0.0
                        return float(value)
                    return objective

                study.optimize(
                    _make_objective(train_data),
                    n_trials=max(self.n_trials // 2, 20),
                    show_progress_bar=False,
                )
                best_params = study.best_trial.params
            else:
                best_params = {}

            train_metrics = self._run_backtest(
                strategy_class, best_params, train_data, exit_config, backtest_config
            )
            test_metrics = self._run_backtest(
                strategy_class, best_params, test_data, exit_config, backtest_config
            )

            split_result = {
                "split_index": split_idx,
                "train_start": str(train_data.index[0]),
                "train_end": str(train_data.index[-1]),
                "test_start": str(test_data.index[0]),
                "test_end": str(test_data.index[-1]),
                "best_params": best_params,
                "train_metrics": train_metrics,
                "test_metrics": test_metrics,
            }
            results.append(split_result)

            logger.info(
                "WF split {}: train {:.4f}, test {:.4f} ({})",
                split_idx,
                train_metrics.get(self.objective_metric, 0.0),
                test_metrics.get(self.objective_metric, 0.0),
                self.objective_metric,
            )

        return results

    # ------------------------------------------------------------------
    # Strategy comparison
    # ------------------------------------------------------------------

    def compare_strategies(
        self,
        strategy_classes: list[Type[BaseStrategy]],
        df: pd.DataFrame,
        exit_config: dict,
        backtest_config: dict,
    ) -> pd.DataFrame:
        """Optimise multiple strategies and return a ranking DataFrame.

        Each strategy is optimised using :meth:`optimize`. The returned
        DataFrame ranks strategies by the objective metric (descending).

        Parameters
        ----------
        strategy_classes : list[Type[BaseStrategy]]
            List of strategy classes to compare.
        df : pd.DataFrame
            OHLCV DataFrame with features.
        exit_config : dict
            Exit-manager configuration.
        backtest_config : dict
            Backtest engine configuration.

        Returns
        -------
        pd.DataFrame
            Ranking table with columns: strategy_name, best_params,
            train_{metric}, validation_{metric}, test_{metric} for every
            computed metric.
        """
        rows: list[dict] = []

        for strategy_class in strategy_classes:
            logger.info("Comparing strategy: {}", strategy_class.__name__)
            result = self.optimize(strategy_class, df, exit_config, backtest_config)

            row: dict[str, Any] = {"strategy_name": result["strategy_name"]}
            row["best_params"] = str(result["best_params"])

            for split_name in ("train", "validation", "test"):
                metrics = result.get(f"{split_name}_metrics", {})
                for key, value in metrics.items():
                    row[f"{split_name}_{key}"] = value

            rows.append(row)

        ranking = pd.DataFrame(rows)

        # Sort by test-set objective metric descending
        sort_col = f"test_{self.objective_metric}"
        if sort_col in ranking.columns:
            ranking = ranking.sort_values(sort_col, ascending=False).reset_index(drop=True)

        logger.info("Strategy ranking:\n{}", ranking.to_string())
        return ranking

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _sample_params(trial: optuna.Trial, param_space: dict) -> dict:
        """Sample parameters for a single Optuna trial.

        The ``param_space`` dict maps parameter names to tuples:
        - ``(low: int, high: int)`` -> ``suggest_int``
        - ``(low: float, high: float)`` -> ``suggest_float``
        """
        params: dict = {}
        for name, bounds in param_space.items():
            low, high = bounds
            if isinstance(low, int) and isinstance(high, int):
                params[name] = trial.suggest_int(name, low, high)
            else:
                params[name] = trial.suggest_float(name, float(low), float(high))
        return params

    @staticmethod
    def _run_backtest(
        strategy_class: Type[BaseStrategy],
        params: dict,
        df: pd.DataFrame,
        exit_config: dict,
        backtest_config: dict,
    ) -> dict:
        """Instantiate a strategy with *params*, generate signals, and backtest.

        Returns the full metrics dictionary from :func:`calc_all_metrics`.
        """
        if df.empty:
            return {}

        strategy = strategy_class(config=params)
        signals = strategy.generate_signals(df)

        if not signals:
            return {
                "total_profit": 0.0,
                "profit_factor": 0.0,
                "expectancy": 0.0,
                "max_drawdown_abs": 0.0,
                "max_drawdown_pct": 0.0,
                "calmar_ratio": 0.0,
                "win_rate": 0.0,
                "avg_win_loss_ratio": 0.0,
                "avg_holding_time_hours": 0.0,
                "high_tp_rate_3rr": 0.0,
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
            }

        exit_manager = ExitManager(exit_config)
        engine = BacktestEngine(backtest_config)
        result = engine.run(df, signals, exit_manager)

        return result.metrics

    def _evaluate_default(
        self,
        strategy_class: Type[BaseStrategy],
        train_df: pd.DataFrame,
        val_df: pd.DataFrame,
        test_df: pd.DataFrame,
        exit_config: dict,
        backtest_config: dict,
    ) -> dict:
        """Evaluate strategy with default (empty) parameters on all splits."""
        train_metrics = self._run_backtest(
            strategy_class, {}, train_df, exit_config, backtest_config
        )
        val_metrics = self._run_backtest(
            strategy_class, {}, val_df, exit_config, backtest_config
        )
        test_metrics = self._run_backtest(
            strategy_class, {}, test_df, exit_config, backtest_config
        )
        return {
            "strategy_name": strategy_class.__name__,
            "best_params": {},
            "train_metrics": train_metrics,
            "validation_metrics": val_metrics,
            "test_metrics": test_metrics,
            "n_trials": 0,
            "best_trial_number": -1,
        }
