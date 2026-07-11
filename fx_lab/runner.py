"""戦略の自動検出・バックテスト実行・評価

自動生成戦略（engine経由）と手動戦略の両方に対応。
"""

import os
import sys
import importlib
import inspect
import logging
from tqdm import tqdm

import pandas as pd
from strategy_base import Strategy
from metrics import evaluate_strategy
from data_loader import load_ohlc
from engine.strategy_loader import load_all_strategies

logger = logging.getLogger(__name__)


def discover_strategies(strategies_dir: str) -> list[type[Strategy]]:
    """strategies_dir内の全.pyファイルからStrategyサブクラスを自動検出

    engine.strategy_loader を使用した高信頼ローダー。
    """
    return load_all_strategies(strategies_dir)


def run_backtest(
    strategy_class: type[Strategy],
    df: pd.DataFrame,
    initial_balance: float,
    spread: float,
    commission: float,
) -> dict:
    """単一の戦略をバックテストし、評価結果を返す"""
    strategy = strategy_class(spread=spread, commission=commission)
    trades = strategy.backtest(df, initial_balance=initial_balance)
    result = evaluate_strategy(trades, initial_balance)
    result["strategy_name"] = strategy.name
    return result


def run_all_backtests(
    data_files: list[dict],
    strategies_dir: str,
    initial_balance: float,
    spread: float,
    commission: float,
) -> list[dict]:
    """全データファイル x 全戦略の組み合わせでバックテスト実行"""
    strategy_classes = discover_strategies(strategies_dir)

    if not strategy_classes:
        logger.warning("戦略が見つかりませんでした")
        return []

    if not data_files:
        logger.warning("データファイルが見つかりませんでした")
        return []

    all_results = []
    total = len(data_files) * len(strategy_classes)

    with tqdm(total=total, desc="バックテスト実行中") as pbar:
        for data_info in data_files:
            symbol = data_info["symbol"]
            timeframe = data_info["timeframe"]
            filepath = data_info["filepath"]

            try:
                df = load_ohlc(filepath)
            except Exception as e:
                logger.error(f"データ読み込み失敗 ({filepath}): {e}")
                pbar.update(len(strategy_classes))
                continue

            for strategy_class in strategy_classes:
                try:
                    result = run_backtest(
                        strategy_class, df, initial_balance, spread, commission
                    )
                    result["symbol"] = symbol
                    result["timeframe"] = timeframe
                    all_results.append(result)
                except Exception as e:
                    logger.error(f"バックテスト失敗 ({strategy_class.name}, {symbol}_{timeframe}): {e}")
                finally:
                    pbar.update(1)

    return all_results
