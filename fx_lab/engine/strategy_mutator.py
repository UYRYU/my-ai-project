"""戦略の突然変異・交差エンジン

上位戦略の特徴を分析し、次世代戦略を生成する。
カテゴリ多様性を保証するための制約付き生成。
"""

import copy
import random
import json
import hashlib
from typing import Any

from engine.strategy_generator import (
    ENTRY_SIGNALS, ENTRY_FILTERS, TP_TYPES, SL_TYPES, EXIT_EXTRAS,
    SIGNAL_CATEGORIES,
    _rand_val, _resolve_block, generate_strategy_config, write_strategy_file,
    _get_signals_by_category,
)


def _mutate_value(value: Any, intensity: float = 0.3) -> Any:
    """値を突然変異させる"""
    if isinstance(value, int):
        delta = max(1, int(abs(value) * intensity))
        return max(1, value + random.randint(-delta, delta))
    elif isinstance(value, float):
        delta = abs(value) * intensity
        return round(max(0.001, value + random.uniform(-delta, delta)), 4)
    elif isinstance(value, bool):
        return value if random.random() > 0.2 else not value
    return value


def mutate_config(config: dict, intensity: float = 0.3) -> dict:
    """戦略設定を突然変異させる"""
    cfg = copy.deepcopy(config)

    # エントリーシグナルのパラメータを変異
    sig = cfg["entry_signal"]
    for key in sig:
        if key in ("type", "category"):
            continue
        if random.random() < 0.5:
            sig[key] = _mutate_value(sig[key], intensity)

    # EMAクロスの制約維持
    if sig.get("type") == "ema_cross":
        s = sig.get("short_period", 5)
        l = sig.get("long_period", 20)
        if s >= l:
            sig["short_period"] = min(s, l)
            sig["long_period"] = max(s, l) + 1

    # RSI逆張りの制約維持
    if sig.get("type") == "rsi_reversal":
        ob = sig.get("overbought", 70)
        os_ = sig.get("oversold", 30)
        if os_ >= ob:
            sig["oversold"] = min(os_, ob) - 5
            sig["overbought"] = max(os_, ob) + 5

    # フィルターの変異
    for filt in cfg.get("entry_filters", []):
        for key in filt:
            if key == "type":
                continue
            if random.random() < 0.4:
                filt[key] = _mutate_value(filt[key], intensity)

    # フィルターの追加/削除 (低確率)
    if random.random() < 0.15 and len(cfg.get("entry_filters", [])) < 3:
        new_filter = _resolve_block(random.choice(ENTRY_FILTERS))
        cfg.setdefault("entry_filters", []).append(new_filter)
    elif random.random() < 0.1 and cfg.get("entry_filters"):
        cfg["entry_filters"].pop(random.randrange(len(cfg["entry_filters"])))

    # エグジットルールの変異
    rules = cfg["exit_rules"]
    for key in rules:
        if key in ("tp_type", "sl_type", "atr_period", "trail_type"):
            continue
        if random.random() < 0.5:
            rules[key] = _mutate_value(rules[key], intensity)

    # エグジット追加オプションのトグル (低確率)
    if random.random() < 0.2:
        extra = _resolve_block(random.choice(EXIT_EXTRAS))
        rules.update(extra)

    # 名前を再生成
    digest = hashlib.md5(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()[:8]
    sig_type = cfg["entry_signal"]["type"]
    cfg["name"] = f"{sig_type}_{digest}"

    return cfg


def crossover_configs(parent_a: dict, parent_b: dict) -> dict:
    """2つの親戦略を交差して子戦略を生成"""
    child = copy.deepcopy(parent_a)

    # エントリーシグナルをどちらかから選択
    if random.random() < 0.5:
        child["entry_signal"] = copy.deepcopy(parent_b["entry_signal"])

    # フィルターを混合
    filters_a = parent_a.get("entry_filters", [])
    filters_b = parent_b.get("entry_filters", [])
    all_filters = filters_a + filters_b
    if all_filters:
        n = random.randint(0, min(2, len(all_filters)))
        child["entry_filters"] = copy.deepcopy(random.sample(all_filters, n))
    else:
        child["entry_filters"] = []

    # エグジットルールを混合
    rules_a = parent_a.get("exit_rules", {})
    rules_b = parent_b.get("exit_rules", {})
    child_rules = {}
    for key in set(list(rules_a.keys()) + list(rules_b.keys())):
        if random.random() < 0.5 and key in rules_b:
            child_rules[key] = copy.deepcopy(rules_b[key])
        elif key in rules_a:
            child_rules[key] = copy.deepcopy(rules_a[key])
        else:
            child_rules[key] = copy.deepcopy(rules_b[key])
    child["exit_rules"] = child_rules

    # 名前を再生成
    digest = hashlib.md5(json.dumps(child, sort_keys=True, default=str).encode()).hexdigest()[:8]
    sig_type = child["entry_signal"]["type"]
    child["name"] = f"{sig_type}_{digest}"

    return child


def analyze_top_features(top_configs: list[dict]) -> dict:
    """上位戦略群の共通特徴を分析"""
    analysis = {
        "signal_types": {},
        "category_types": {},
        "filter_types": {},
        "avg_params": {},
    }

    for cfg in top_configs:
        sig_type = cfg["entry_signal"]["type"]
        analysis["signal_types"][sig_type] = analysis["signal_types"].get(sig_type, 0) + 1

        cat = cfg["entry_signal"].get("category", "unknown")
        analysis["category_types"][cat] = analysis["category_types"].get(cat, 0) + 1

        for filt in cfg.get("entry_filters", []):
            ft = filt["type"]
            analysis["filter_types"][ft] = analysis["filter_types"].get(ft, 0) + 1

    return analysis


def generate_next_generation(
    top_configs: list[dict],
    count: int = 50,
    mutation_rate: float = 0.55,
    crossover_rate: float = 0.25,
    random_rate: float = 0.20,
    base_seed: int = 0,
) -> list[dict]:
    """上位戦略をもとに次世代戦略を生成

    カテゴリ多様性を保証:
    - ランダム生成枠の一部を、上位に含まれないカテゴリに割り当てる
    - 各カテゴリの上限 = count / カテゴリ数 + 5
    """
    random.seed(base_seed)
    next_gen = []
    names_seen = set()

    categories = list(SIGNAL_CATEGORIES.keys())
    max_per_category = (count // len(categories)) + 5
    category_counts: dict[str, int] = {cat: 0 for cat in categories}

    n_mutation = int(count * mutation_rate)
    n_crossover = int(count * crossover_rate)
    n_random = count - n_mutation - n_crossover

    def _add(cfg: dict) -> bool:
        if cfg["name"] in names_seen:
            return False
        cat = cfg.get("entry_signal", {}).get("category", "unknown")
        if cat in category_counts and category_counts[cat] >= max_per_category:
            return False
        names_seen.add(cfg["name"])
        category_counts[cat] = category_counts.get(cat, 0) + 1
        next_gen.append(cfg)
        return True

    # 突然変異
    for i in range(n_mutation):
        parent = random.choice(top_configs)
        intensity = random.uniform(0.1, 0.5)
        child = mutate_config(parent, intensity=intensity)
        _add(child)

    # 交差
    if len(top_configs) >= 2:
        for i in range(n_crossover):
            pa, pb = random.sample(top_configs, 2)
            child = crossover_configs(pa, pb)
            child = mutate_config(child, intensity=0.1)
            _add(child)

    # ランダム生成 (カテゴリバランスを取る)
    # まず、上位に含まれないカテゴリを優先
    top_categories = set()
    for cfg in top_configs:
        top_categories.add(cfg.get("entry_signal", {}).get("category", "unknown"))

    underrepresented = [cat for cat in categories if cat not in top_categories]

    for cat in underrepresented:
        signals = _get_signals_by_category(cat)
        if signals and len(next_gen) < count:
            for _ in range(max(2, n_random // len(categories))):
                sig_template = random.choice(signals)
                cfg = generate_strategy_config(seed=base_seed + 10000 + len(next_gen), sig_template=sig_template)
                _add(cfg)

    # 残りはランダム
    for i in range(n_random):
        cfg = generate_strategy_config(seed=base_seed + 20000 + i)
        _add(cfg)

    # 不足分はランダムで補充
    extra_seed = base_seed + 50000
    while len(next_gen) < count:
        cfg = generate_strategy_config(seed=extra_seed)
        extra_seed += 1
        if cfg["name"] not in names_seen:
            names_seen.add(cfg["name"])
            next_gen.append(cfg)

    return next_gen[:count]
