"""戦略自動生成エンジン

ビルディングブロックをランダムに組み合わせて戦略設定を大量生成する。
カテゴリごとの生成数上限で多様性を保証する。
"""

import os
import json
import random
import hashlib
from typing import Any


# ================================================================
# ビルディングブロック定義
# ================================================================

# カテゴリ分類 (カテゴリ → シグナルタイプのリスト)
SIGNAL_CATEGORIES = {
    "trend_follow": ["ema_cross", "rsi_trend", "momentum"],
    "mean_reversion": ["rsi_reversal", "bb_bounce", "wick_reversal", "consecutive_reversal"],
    "breakout": ["bb_break", "donchian_break", "atr_break", "hilo_break"],
}

ENTRY_SIGNALS = [
    # === トレンドフォロー系 ===
    # EMAクロス
    {"type": "ema_cross", "category": "trend_follow",
     "short_period": (3, 15), "long_period": (15, 60)},
    # RSI順張り (50超え/割れ)
    {"type": "rsi_trend", "category": "trend_follow",
     "period": (7, 21)},
    # モメンタム
    {"type": "momentum", "category": "trend_follow",
     "period": (5, 20)},

    # === 平均回帰系 ===
    # RSI逆張り
    {"type": "rsi_reversal", "category": "mean_reversion",
     "period": (7, 21), "oversold": (20, 35), "overbought": (65, 80)},
    # BB反発
    {"type": "bb_bounce", "category": "mean_reversion",
     "period": (10, 30), "std_mult": (1.5, 3.0)},
    # ヒゲ反転 (長いヒゲ後の反転)
    {"type": "wick_reversal", "category": "mean_reversion",
     "wick_ratio": (1.5, 4.0), "min_wick_atr": (0.3, 1.5), "atr_period": (7, 21)},
    # 連続陽線/陰線後の反転
    {"type": "consecutive_reversal", "category": "mean_reversion",
     "consecutive_count": (3, 7)},

    # === ブレイクアウト系 ===
    # BBブレイク (拡張ブレイク)
    {"type": "bb_break", "category": "breakout",
     "period": (10, 30), "std_mult": (1.5, 3.0)},
    # ドンチャンブレイク
    {"type": "donchian_break", "category": "breakout",
     "period": (10, 40)},
    # ATR急増ブレイク
    {"type": "atr_break", "category": "breakout",
     "period": (7, 21), "multiplier": (1.0, 3.0)},
    # 直近高値安値ブレイク
    {"type": "hilo_break", "category": "breakout",
     "lookback": (5, 30), "confirm_bars": (1, 3)},
]

ENTRY_FILTERS = [
    # 時間帯フィルター (汎用)
    {"type": "time_filter", "start_hour": (7, 10), "end_hour": (18, 22)},
    # セッションフィルター (東京/ロンドン/NY)
    {"type": "session_filter",
     "session": ("tokyo", "london", "newyork", "tokyo_london", "london_ny")},
    # ATRボラティリティフィルター
    {"type": "atr_filter", "min_atr": (0.01, 0.1), "max_atr": (0.3, 1.0)},
    # 上位足トレンドフィルター (M5方向一致)
    {"type": "htf_trend", "period": (30, 100)},
    # RSIレンジフィルター (極端な値域を避ける)
    {"type": "rsi_range_filter", "rsi_period": (14, 21),
     "rsi_low": (25, 40), "rsi_high": (60, 75)},
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
    # 建値移動
    {"breakeven": True, "be_trigger_pips": (0.1, 0.4)},
    # トレーリング(固定)
    {"trailing": True, "trail_type": "fixed", "trail_distance": (0.1, 0.4)},
    # トレーリング(ATR)
    {"trailing": True, "trail_type": "atr_mult", "trail_atr_mult": (0.5, 2.0)},
    # 時間切れ決済
    {"max_bars": (30, 300)},
    # 逆シグナル決済
    {"reverse_signal_exit": True},
    # 分割利確 (TP距離の半分で半分クローズ)
    {"partial_tp": True, "partial_ratio": (0.3, 0.7), "partial_tp_ratio": (0.4, 0.6)},
    # 連敗停止
    {"loss_streak_stop": True, "max_consecutive_losses": (3, 8)},
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
        if isinstance(lo, str):
            # 文字列のtuple → ランダム選択
            return random.choice(spec)
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
# カテゴリ管理
# ================================================================

def _get_signals_by_category(category: str) -> list[dict]:
    """カテゴリに属するシグナルテンプレートを返す"""
    return [s for s in ENTRY_SIGNALS if s.get("category") == category]


def _pick_signal_balanced(category_counts: dict, max_per_category: int) -> dict:
    """カテゴリバランスを考慮してシグナルを選択"""
    categories = list(SIGNAL_CATEGORIES.keys())
    random.shuffle(categories)

    for cat in categories:
        if category_counts.get(cat, 0) < max_per_category:
            signals = _get_signals_by_category(cat)
            if signals:
                return random.choice(signals)

    # 全カテゴリ上限到達 → 最も少ないカテゴリから選択
    min_cat = min(categories, key=lambda c: category_counts.get(c, 0))
    signals = _get_signals_by_category(min_cat)
    return random.choice(signals) if signals else random.choice(ENTRY_SIGNALS)


# ================================================================
# 戦略生成
# ================================================================

def generate_strategy_config(seed: int | None = None, sig_template: dict | None = None) -> dict:
    """ランダムに1つの戦略設定を生成

    sig_template: 指定されたらそのシグナルテンプレートを使用
    """
    if seed is not None:
        random.seed(seed)

    # エントリーシグナル選択
    if sig_template is None:
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
    """複数の戦略設定を一括生成 (カテゴリ多様性を保証)"""
    configs = []
    names_seen = set()
    attempts = 0
    max_attempts = count * 5

    categories = list(SIGNAL_CATEGORIES.keys())
    n_categories = len(categories)
    max_per_category = (count // n_categories) + 2  # 各カテゴリの上限

    category_counts: dict[str, int] = {cat: 0 for cat in categories}

    while len(configs) < count and attempts < max_attempts:
        seed = base_seed + attempts
        random.seed(seed)

        # カテゴリバランスを考慮してシグナル選択
        sig_template = _pick_signal_balanced(category_counts, max_per_category)
        cfg = generate_strategy_config(seed=seed, sig_template=sig_template)

        if cfg["name"] not in names_seen:
            names_seen.add(cfg["name"])
            cat = cfg["entry_signal"].get("category", "unknown")
            category_counts[cat] = category_counts.get(cat, 0) + 1
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


def get_category_distribution(configs: list[dict]) -> dict[str, int]:
    """戦略リストのカテゴリ分布を返す"""
    dist: dict[str, int] = {}
    for cfg in configs:
        cat = cfg.get("entry_signal", {}).get("category", "unknown")
        dist[cat] = dist.get(cat, 0) + 1
    return dist
