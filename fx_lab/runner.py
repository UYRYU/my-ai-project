"""戦略の自動検出・バックテスト実行・評価"""

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

logger = logging.getLogger(__name__)


def discover_strategies(strategies_dir: str) -> list[type[Strategy]]:
    """strategies_dir内の全.pyファイルからStrategyサブクラスを自動検出"""
    strategy_classes = []

    if not os.path.isdir(strategies_dir):
        logger.warning(f"戦略ディレクトリが見つかりません: {strategies_dir}")
        return strategy_classes

    # strategies_dirの親をsys.pathに追加
    parent_dir = os.path.dirname(os.path.abspath(strategies_dir))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

    for filename in sorted(os.listdir(strategies_dir)):
        if not filename.endswith(".py") or filename.startswith("_"):
            continue

        module_name = filename.replace(".py", "")
        module_path = f"strategies.generated.{module_name}"

        try:
            module = importlib.import_module(module_path)
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (inspect.isclass(attr)
                        and issubclass(attr, Strategy)
                        and attr is not Strategy):
                    strategy_classes.append(attr)
                    logger.info(f"戦略を検出: {attr.name} ({filename})")
        except Exception as e:
            logger.error(f"戦略の読み込みに失敗 ({filename}): {e}")

    return strategy_classes


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
