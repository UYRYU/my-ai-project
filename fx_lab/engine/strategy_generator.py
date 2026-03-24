"""戦略自動生成エンジン

ビルディングブロックをランダムに組み合わせて戦略設定を大量生成する。
"""

import os
import json
import random
import hashlib
from typing import Any


# ================================================================
# ビルディングブロック定義
# ================================================================

ENTRY_SIGNALS = [
    # EMAクロス系
    {"type": "ema_cross", "short_period": (3, 15), "long_period": (15, 60)},
    # RSI逆張り
    {"type": "rsi_reversal", "period": (7, 21), "oversold": (20, 35), "overbought": (65, 80)},
    # RSI順張り
    {"type": "rsi_trend", "period": (7, 21)},
    # BB反発
    {"type": "bb_bounce", "period": (10, 30), "std_mult": (1.5, 3.0)},
    # BBブレイク
    {"type": "bb_break", "period": (10, 30), "std_mult": (1.5, 3.0)},
    # ドンチャンブレイク
    {"type": "donchian_break", "period": (10, 40)},
    # ATRブレイク
    {"type": "atr_break", "period": (7, 21), "multiplier": (1.0, 3.0)},
    # モメンタム
    {"type": "momentum", "period": (5, 20)},
]

ENTRY_FILTERS = [
    {"type": "time_filter", "start_hour": (7, 10), "end_hour": (18, 22)},
    {"type": "atr_filter", "min_atr": (0.01, 0.1), "max_atr": (0.3, 1.0)},
    {"type": "htf_trend", "period": (30, 100)},
]

TP_TYPES = [
    {"tp_type": "fixed", "tp_pips": (0.1, 0.8)},
    {"tp_type": "atr_mult", "tp_atr_mult": (1.0, 4.0)},
]

SL_TYPES = [
    {"sl_type": "fixed", "sl_pips": (0.1, 0.5)},
    {"sl_type": "atr_mult", "sl_atr_mult": (0.5, 3.0)},
]

EXIT_EXTRAS = [
    {"breakeven": True, "be_trigger_pips": (0.1, 0.4)},
    {"trailing": True, "trail_type": "fixed", "trail_distance": (0.1, 0.4)},
    {"trailing": True, "trail_type": "atr_mult", "trail_atr_mult": (0.5, 2.0)},
    {"max_bars": (30, 300)},
    {"reverse_signal_exit": True},
]


# ================================================================
# ユーティリティ
# ================================================================

def _rand_val(spec: Any) -> Any:
    """仕様からランダム値を生成。tupleなら範囲、その他はそのまま。"""
    if isinstance(spec, tuple) and len(spec) == 2:
        lo, hi = spec
        if isinstance(lo, int) and isinstance(hi, int):
            return random.randint(lo, hi)
        return round(random.uniform(lo, hi), 4)
    return spec


def _resolve_block(template: dict) -> dict:
    """テンプレートの範囲指定を具体値に解決"""
    return {k: _rand_val(v) for k, v in template.items()}


def _make_name(config: dict) -> str:
    """設定からユニークな名前を生成"""
    sig_type = config["entry_signal"]["type"]
    digest = hashlib.md5(json.dumps(config, sort_keys=True, default=str).encode()).hexdigest()[:8]
    return f"{sig_type}_{digest}"


# ================================================================
# 戦略生成
# ================================================================

def generate_strategy_config(seed: int | None = None) -> dict:
    """ランダムに1つの戦略設定を生成"""
    if seed is not None:
        random.seed(seed)

    # エントリーシグナル選択
    sig_template = random.choice(ENTRY_SIGNALS)
    entry_signal = _resolve_block(sig_template)

    # EMAクロスの場合、short < long を保証
    if entry_signal.get("type") == "ema_cross":
        s, l = entry_signal["short_period"], entry_signal["long_period"]
        if s >= l:
            entry_signal["short_period"] = min(s, l)
            entry_signal["long_period"] = max(s, l) + 1

    # RSI逆張りの場合、oversold < overbought を保証
    if entry_signal.get("type") == "rsi_reversal":
        ob = entry_signal.get("overbought", 70)
        os_ = entry_signal.get("oversold", 30)
        if os_ >= ob:
            entry_signal["oversold"] = min(os_, ob) - 5
            entry_signal["overbought"] = max(os_, ob) + 5

    # フィルター (0〜2個ランダム)
    num_filters = random.randint(0, 2)
    filters = []
    if num_filters > 0:
        chosen = random.sample(ENTRY_FILTERS, min(num_filters, len(ENTRY_FILTERS)))
        for ft in chosen:
            filters.append(_resolve_block(ft))

    # TP/SL
    tp_config = _resolve_block(random.choice(TP_TYPES))
    sl_config = _resolve_block(random.choice(SL_TYPES))

    # ATR期間
    atr_period = random.randint(7, 21)

    # エグジット追加オプション (0〜2個)
    num_extras = random.randint(0, 2)
    extras = {}
    if num_extras > 0:
        chosen_extras = random.sample(EXIT_EXTRAS, min(num_extras, len(EXIT_EXTRAS)))
        for ext in chosen_extras:
            extras.update(_resolve_block(ext))

    exit_rules = {**tp_config, **sl_config, "atr_period": atr_period, **extras}

    config = {
        "entry_signal": entry_signal,
        "entry_filters": filters,
        "exit_rules": exit_rules,
    }
    config["name"] = _make_name(config)

    return config


def generate_many(count: int, base_seed: int = 42) -> list[dict]:
    """複数の戦略設定を一括生成"""
    configs = []
    names_seen = set()
    attempts = 0
    max_attempts = count * 5

    while len(configs) < count and attempts < max_attempts:
        seed = base_seed + attempts
        cfg = generate_strategy_config(seed=seed)
        if cfg["name"] not in names_seen:
            names_seen.add(cfg["name"])
            configs.append(cfg)
        attempts += 1

    return configs


# ================================================================
# ファイル書き出し
# ================================================================

def write_strategy_file(config: dict, output_dir: str) -> str:
    """戦略設定をPythonファイルとして書き出す"""
    os.makedirs(output_dir, exist_ok=True)
    name = config["name"]
    filepath = os.path.join(output_dir, f"{name}.py")

    # repr()を使ってPythonリテラルとして出力（True/Falseが正しく出る）
    import pprint
    config_repr = pprint.pformat(config, indent=4, width=100)

    code = f'''"""自動生成戦略: {name}"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {config_repr}

class GeneratedStrategy(ConfigurableStrategy):
    name = "{name}"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
'''

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(code)

    return filepath


def generate_and_write(count: int, output_dir: str, base_seed: int = 42) -> list[str]:
    """戦略を生成してファイルに書き出す"""
    configs = generate_many(count, base_seed=base_seed)
    paths = []
    for cfg in configs:
        path = write_strategy_file(cfg, output_dir)
        paths.append(path)
    return paths
