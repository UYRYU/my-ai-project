"""戦略ファイルの動的読み込み"""

import os
import sys
import importlib
import importlib.util
import inspect
import json
import logging

from strategy_base import Strategy

logger = logging.getLogger(__name__)


def load_strategy_from_file(filepath: str) -> type[Strategy] | None:
    """単一のPythonファイルから Strategy サブクラスを読み込む"""
    module_name = os.path.splitext(os.path.basename(filepath))[0]
    spec = importlib.util.spec_from_file_location(module_name, filepath)
    if spec is None or spec.loader is None:
        return None

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        logger.error(f"モジュール読み込み失敗 ({filepath}): {e}")
        return None

    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if (inspect.isclass(attr)
                and issubclass(attr, Strategy)
                and attr is not Strategy
                and attr.__module__ == module_name):
            return attr

    return None


def load_all_strategies(strategies_dir: str) -> list[type[Strategy]]:
    """ディレクトリ内の全戦略クラスを読み込む"""
    classes = []
    if not os.path.isdir(strategies_dir):
        logger.warning(f"ディレクトリが見つかりません: {strategies_dir}")
        return classes

    for filename in sorted(os.listdir(strategies_dir)):
        if not filename.endswith(".py") or filename.startswith("_"):
            continue
        filepath = os.path.join(strategies_dir, filename)
        cls = load_strategy_from_file(filepath)
        if cls is not None:
            classes.append(cls)
        else:
            logger.warning(f"戦略クラスが見つかりません: {filename}")

    logger.info(f"{len(classes)} 個の戦略を読み込みました ({strategies_dir})")
    return classes


def extract_config_from_file(filepath: str) -> dict | None:
    """戦略ファイルからCONFIG dictを抽出する"""
    module_name = os.path.splitext(os.path.basename(filepath))[0]
    spec = importlib.util.spec_from_file_location(module_name, filepath)
    if spec is None or spec.loader is None:
        return None

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        logger.error(f"CONFIG抽出失敗 ({filepath}): {e}")
        return None

    config = getattr(module, "CONFIG", None)
    if isinstance(config, dict):
        return config
    return None


def extract_all_configs(strategies_dir: str) -> list[dict]:
    """ディレクトリ内の全戦略からCONFIGを抽出"""
    configs = []
    if not os.path.isdir(strategies_dir):
        return configs

    for filename in sorted(os.listdir(strategies_dir)):
        if not filename.endswith(".py") or filename.startswith("_"):
            continue
        filepath = os.path.join(strategies_dir, filename)
        cfg = extract_config_from_file(filepath)
        if cfg is not None:
            configs.append(cfg)

    return configs
