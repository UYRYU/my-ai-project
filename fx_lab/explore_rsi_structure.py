"""RSI逆張り + 構造フィルタ 深掘り探索

RSI(14) 閾値28/72 を固定し、以下の構造フィルタの組み合わせで50-100戦略を生成:
  ① H1トレンド一致フィルタ (htf_trend)
  ② BB外側タッチフィルタ (bb_touch_filter)
  ③ ATR低ボラフィルタ (atr_low_vola_filter)
  ④ ヒゲ反転フィルタ (wick_direction_filter)

対象: GBPJPY_M5, USDJPY_M5 / london, newyork
評価: OOS PF >= 1.15, MaxDD <= 15%, trades >= 300
"""

import os
import sys
import itertools
import hashlib
import json
import logging
import random
from collections import Counter

import pandas as pd
import numpy as np
from tqdm import tqdm

from engine.strategy_generator import _make_name
from engine.configurable_strategy import ConfigurableStrategy
from data_loader import load_ohlc, discover_data_files
from metrics import evaluate_strategy
from engine.evolution import split_is_oos, _classify_session

logger = logging.getLogger(__name__)


# ================================================================
# 固定パラメータ
# ================================================================
RSI_PERIOD = 14
OVERSOLD = 28
OVERBOUGHT = 72

TARGET_SYMBOLS = ["GBPJPY", "USDJPY"]
TARGET_TIMEFRAME = "M5"
TARGET_SESSIONS = ["london", "newyork"]

# 評価基準
EVAL_MIN_PF = 1.15
EVAL_MAX_DD = 15.0
EVAL_MIN_TRADES = 300


# ================================================================
# 構造フィルタ定義
# ================================================================

# ① H1トレンド一致フィルタ (reversionモード: H1上昇中ショート禁止、H1下降中ロング禁止)
HTF_TREND_OPTIONS = [
    {"type": "htf_trend", "period": 12, "mode": "reversion"},   # 60本EMA (H1相当)
    {"type": "htf_trend", "period": 24, "mode": "reversion"},   # 120本EMA (H2相当)
    {"type": "htf_trend", "period": 6, "mode": "reversion"},    # 30本EMA (30分相当)
]

# ② BB外側タッチフィルタ
BB_TOUCH_OPTIONS = [
    {"type": "bb_touch_filter", "period": 20, "std_mult": 2.0},
    {"type": "bb_touch_filter", "period": 20, "std_mult": 1.5},
    {"type": "bb_touch_filter", "period": 14, "std_mult": 2.0},
    {"type": "bb_touch_filter", "period": 30, "std_mult": 2.0},
]

# ③ ATR低ボラフィルタ
ATR_LOW_VOLA_OPTIONS = [
    {"type": "atr_low_vola_filter", "lookback": 60},
    {"type": "atr_low_vola_filter", "lookback": 100},
    {"type": "atr_low_vola_filter", "lookback": 200},
]

# ④ ヒゲ反転フィルタ
WICK_DIRECTION_OPTIONS = [
    {"type": "wick_direction_filter", "wick_ratio": 0.8},
    {"type": "wick_direction_filter", "wick_ratio": 1.0},
    {"type": "wick_direction_filter", "wick_ratio": 1.5},
]

# TP/SL (前回の結果から有望なものに絞る)
TP_CONFIGS = [
    {"tp_type": "atr_mult", "tp_atr_mult": 1.5},
    {"tp_type": "atr_mult", "tp_atr_mult": 2.0},
    {"tp_type": "atr_mult", "tp_atr_mult": 2.5},
    {"tp_type": "atr_mult", "tp_atr_mult": 3.0},
    {"tp_type": "fixed", "tp_pips": 0.3},
    {"tp_type": "fixed", "tp_pips": 0.5},
]

SL_CONFIGS = [
    {"sl_type": "fixed", "sl_pips": 0.15},
    {"sl_type": "fixed", "sl_pips": 0.25},
    {"sl_type": "fixed", "sl_pips": 0.35},
    {"sl_type": "atr_mult", "sl_atr_mult": 1.0},
    {"sl_type": "atr_mult", "sl_atr_mult": 1.5},
]

# 建値移動
BREAKEVEN_OPTIONS = [
    {},
    {"breakeven": True, "be_trigger_pips": 0.15},
    {"breakeven": True, "be_trigger_pips": 0.25},
]

# 時間切れ
MAX_BARS_OPTIONS = [
    {},
    {"max_bars": 60},
    {"max_bars": 120},
]

ATR_PERIODS = [12, 14]


def _generate_structure_configs(target_count: int = 80) -> list[dict]:
    """構造フィルタ付きRSI逆張り戦略を体系的に生成

    3層構造:
      Layer A: フィルタ1個のみ (各フィルタバリエーション × セッション × exit)  ~40個
      Layer B: フィルタ2個組み合わせ                                          ~30個
      Layer C: フィルタなし (RSI+セッションのみ = ベースライン)                ~10個
    """
    random.seed(123)

    session_filters = [
        [{"type": "session_filter", "session": "london"}],
        [{"type": "session_filter", "session": "newyork"}],
    ]

    # 全構造フィルタをフラットリスト化
    all_struct_options = {
        "htf": HTF_TREND_OPTIONS,
        "bb_touch": BB_TOUCH_OPTIONS,
        "atr_low_vola": ATR_LOW_VOLA_OPTIONS,
        "wick_dir": WICK_DIRECTION_OPTIONS,
    }

    exit_combos = list(itertools.product(
        TP_CONFIGS, SL_CONFIGS, ATR_PERIODS, BREAKEVEN_OPTIONS, MAX_BARS_OPTIONS,
    ))
    random.shuffle(exit_combos)

    configs = []
    seen_hashes = set()

    def _try_add(struct_filters, sess_filt, exit_combo):
        tp_cfg, sl_cfg, atr_period, be_opt, mb_opt = exit_combo
        all_filters = sess_filt + struct_filters
        exit_rules = {**tp_cfg, **sl_cfg, "atr_period": atr_period, **be_opt, **mb_opt}
        config = {
            "entry_signal": {
                "type": "rsi_reversal",
                "category": "mean_reversion",
                "period": RSI_PERIOD,
                "oversold": OVERSOLD,
                "overbought": OVERBOUGHT,
            },
            "entry_filters": all_filters,
            "exit_rules": exit_rules,
        }
        config["name"] = _make_name(config)
        cfg_hash = hashlib.md5(
            json.dumps(config, sort_keys=True, default=str).encode()
        ).hexdigest()
        if cfg_hash not in seen_hashes:
            seen_hashes.add(cfg_hash)
            configs.append(config)
            return True
        return False

    # Layer C: ベースライン (フィルタなし) ~10個
    for _ in range(10):
        sess = random.choice(session_filters)
        exit_c = random.choice(exit_combos)
        _try_add([], sess, exit_c)

    # Layer A: フィルタ1個のみ ~40個 (各フィルタカテゴリから均等)
    target_per_cat = 10
    for cat_name, options in all_struct_options.items():
        count = 0
        attempts = 0
        while count < target_per_cat and attempts < target_per_cat * 10:
            attempts += 1
            filt = random.choice(options)
            sess = random.choice(session_filters)
            exit_c = random.choice(exit_combos)
            if _try_add([filt], sess, exit_c):
                count += 1

    # Layer B: フィルタ2個組み合わせ ~30個
    cat_names = list(all_struct_options.keys())
    cat_pairs = list(itertools.combinations(cat_names, 2))
    target_per_pair = 5
    for c1, c2 in cat_pairs:
        count = 0
        attempts = 0
        while count < target_per_pair and attempts < target_per_pair * 10:
            attempts += 1
            f1 = random.choice(all_struct_options[c1])
            f2 = random.choice(all_struct_options[c2])
            sess = random.choice(session_filters)
            exit_c = random.choice(exit_combos)
            if _try_add([f1, f2], sess, exit_c):
                count += 1

    logger.info(f"構造フィルタ付きRSI戦略を {len(configs)} 個生成")
    return configs


def _describe_filters(config: dict) -> dict:
    """configから各フィルタの有無・パラメータを抽出"""
    filters = config.get("entry_filters", [])
    info = {
        "session": "all",
        "htf_period": 0,
        "bb_touch_period": 0,
        "bb_touch_std": 0.0,
        "atr_low_vola_lb": 0,
        "wick_ratio": 0.0,
        "has_htf": False,
        "has_bb_touch": False,
        "has_atr_low_vola": False,
        "has_wick_dir": False,
        "n_struct_filters": 0,
    }
    n_struct = 0
    for f in filters:
        ft = f.get("type", "")
        if ft == "session_filter":
            info["session"] = f.get("session", "all")
        elif ft == "htf_trend":
            info["htf_period"] = f.get("period", 0)
            info["has_htf"] = True
            n_struct += 1
        elif ft == "bb_touch_filter":
            info["bb_touch_period"] = f.get("period", 0)
            info["bb_touch_std"] = f.get("std_mult", 0.0)
            info["has_bb_touch"] = True
            n_struct += 1
        elif ft == "atr_low_vola_filter":
            info["atr_low_vola_lb"] = f.get("lookback", 0)
            info["has_atr_low_vola"] = True
            n_struct += 1
        elif ft == "wick_direction_filter":
            info["wick_ratio"] = f.get("wick_ratio", 0.0)
            info["has_wick_dir"] = True
            n_struct += 1
    info["n_struct_filters"] = n_struct
    return info


def _run_oos_backtest(
    configs: list[dict],
    data_files: list[dict],
    initial_balance: float,
    spread: float,
    commission: float,
    is_ratio: float = 0.7,
) -> list[dict]:
    """OOSバックテスト実行"""
    results = []
    total = len(configs) * len(data_files)

    with tqdm(total=total, desc="  構造フィルタOOSテスト") as pbar:
        for data_info in data_files:
            symbol = data_info["symbol"]
            timeframe = data_info["timeframe"]

            try:
                df = load_ohlc(data_info["filepath"])
                _, oos_df = split_is_oos(df, is_ratio=is_ratio)
            except Exception as e:
                logger.error(f"データ読み込み失敗: {symbol}_{timeframe}: {e}")
                pbar.update(len(configs))
                continue

            for cfg in configs:
                try:
                    strat = ConfigurableStrategy(
                        config=cfg, spread=spread, commission=commission
                    )
                    trades = strat.backtest(oos_df, initial_balance=initial_balance)
                    result = evaluate_strategy(trades, initial_balance)
                    result["strategy_name"] = cfg["name"]
                    result["symbol"] = symbol
                    result["timeframe"] = timeframe

                    # フィルタ情報
                    finfo = _describe_filters(cfg)
                    result.update(finfo)

                    # TP/SL情報
                    result["tp_type"] = cfg["exit_rules"].get("tp_type", "?")
                    result["sl_type"] = cfg["exit_rules"].get("sl_type", "?")
                    result["has_breakeven"] = bool(cfg["exit_rules"].get("breakeven"))
                    result["max_bars"] = cfg["exit_rules"].get("max_bars", 0)

                    # 平均保有時間 (分)
                    result["avg_hold_min"] = round(result["avg_holding_seconds"] / 60, 1)

                    # セッション別PNL
                    if trades:
                        session_pnl = {"tokyo": 0.0, "london": 0.0, "newyork": 0.0}
                        session_count = {"tokyo": 0, "london": 0, "newyork": 0}
                        for t in trades:
                            sess = _classify_session(t.entry_time.hour)
                            session_pnl[sess] += t.pnl
                            session_count[sess] += 1
                        result["pnl_tokyo"] = round(session_pnl["tokyo"], 2)
                        result["pnl_london"] = round(session_pnl["london"], 2)
                        result["pnl_newyork"] = round(session_pnl["newyork"], 2)
                        result["trades_tokyo"] = session_count["tokyo"]
                        result["trades_london"] = session_count["london"]
                        result["trades_newyork"] = session_count["newyork"]
                    else:
                        for k in ["pnl_tokyo", "pnl_london", "pnl_newyork"]:
                            result[k] = 0.0
                        for k in ["trades_tokyo", "trades_london", "trades_newyork"]:
                            result[k] = 0

                    results.append(result)
                except Exception as e:
                    logger.error(f"バックテスト失敗 ({cfg['name']}, {symbol}_{timeframe}): {e}")
                finally:
                    pbar.update(1)

    return results


def _cap_pf(val: float, cap: float = 10.0) -> float:
    if val == float("inf") or val != val:
        return cap
    return min(val, cap)


def run_structure_exploration(settings: dict) -> None:
    """構造フィルタ付きRSI逆張り探索のメイン"""
    initial_balance = settings.get("initial_balance", 100000)
    spread = settings.get("spread", 0.02)
    commission = settings.get("commission", 0.005)
    data_dir = settings.get("data_dir", "data/raw")
    results_dir = settings.get("results_dir", "results")
    is_ratio = settings.get("research", {}).get("is_ratio", 0.7)

    ranked_dir = os.path.join(results_dir, "ranked")
    os.makedirs(ranked_dir, exist_ok=True)

    # 対象データファイルのみ抽出
    all_data_files = discover_data_files(data_dir)
    data_files = [
        d for d in all_data_files
        if d["symbol"] in TARGET_SYMBOLS and d["timeframe"] == TARGET_TIMEFRAME
    ]
    if not data_files:
        logger.error("対象データファイルが見つかりません")
        return

    print(f"\n{'='*70}")
    print(f"  RSI逆張り + 構造フィルタ 深掘り探索")
    print(f"{'='*70}")
    print(f"  RSI設定: RSI({RSI_PERIOD}), 閾値 {OVERSOLD}/{OVERBOUGHT}")
    print(f"  対象: {', '.join(TARGET_SYMBOLS)} × {TARGET_TIMEFRAME}")
    print(f"  セッション: {', '.join(TARGET_SESSIONS)}")
    print(f"  評価基準: PF≥{EVAL_MIN_PF}, DD≤{EVAL_MAX_DD}%, trades≥{EVAL_MIN_TRADES}")
    print(f"  データ:")
    for d in data_files:
        print(f"    - {d['symbol']}_{d['timeframe']}")

    # Phase 1: 戦略生成
    print(f"\n  Phase 1: 構造フィルタ付き戦略生成...")
    configs = _generate_structure_configs(target_count=80)
    print(f"  生成数: {len(configs)} 個")

    # フィルタ分布を表示
    filter_stats = {"htf": 0, "bb_touch": 0, "atr_low_vola": 0, "wick_dir": 0}
    session_stats = Counter()
    n_struct_stats = Counter()
    for cfg in configs:
        finfo = _describe_filters(cfg)
        if finfo["has_htf"]: filter_stats["htf"] += 1
        if finfo["has_bb_touch"]: filter_stats["bb_touch"] += 1
        if finfo["has_atr_low_vola"]: filter_stats["atr_low_vola"] += 1
        if finfo["has_wick_dir"]: filter_stats["wick_dir"] += 1
        session_stats[finfo["session"]] += 1
        n_struct_stats[finfo["n_struct_filters"]] += 1

    print(f"  構造フィルタ分布: {dict(filter_stats)}")
    print(f"  セッション分布: {dict(session_stats)}")
    print(f"  フィルタ数分布: {dict(sorted(n_struct_stats.items()))}")

    # Phase 2: OOSバックテスト
    total_tests = len(configs) * len(data_files)
    print(f"\n  Phase 2: OOSバックテスト ({len(configs)} × {len(data_files)} = {total_tests} テスト)")
    all_results = _run_oos_backtest(
        configs, data_files, initial_balance, spread, commission, is_ratio=is_ratio,
    )
    print(f"  結果数: {len(all_results)}")

    if not all_results:
        print("  結果なし。終了。")
        return

    # 全結果保存
    all_df = pd.DataFrame(all_results)
    all_csv = os.path.join(results_dir, "rsi_structure_all.csv")
    all_df.to_csv(all_csv, index=False, encoding="utf-8-sig")
    print(f"  全結果保存: {all_csv}")

    # Phase 3: 評価基準でフィルタリング
    print(f"\n  Phase 3: 候補抽出 (PF≥{EVAL_MIN_PF}, DD≤{EVAL_MAX_DD}%, trades≥{EVAL_MIN_TRADES})")
    df = pd.DataFrame(all_results)
    finite_mask = np.isfinite(df["pf"])
    candidates = df[
        finite_mask
        & (df["pf"] >= EVAL_MIN_PF)
        & (df["max_dd_pct"] <= EVAL_MAX_DD)
        & (df["trade_count"] >= EVAL_MIN_TRADES)
    ].copy().sort_values("pf", ascending=False).reset_index(drop=True)

    print(f"  候補数: {len(candidates)}")

    # 候補保存
    output_cols = [
        "strategy_name", "symbol", "timeframe", "session",
        "pf", "winrate", "max_dd_pct", "trade_count", "avg_hold_min",
        "total_pnl", "expectancy", "payoff_ratio",
        "max_consecutive_losses",
        "has_htf", "htf_period",
        "has_bb_touch", "bb_touch_period", "bb_touch_std",
        "has_atr_low_vola", "atr_low_vola_lb",
        "has_wick_dir", "wick_ratio",
        "n_struct_filters",
        "tp_type", "sl_type", "has_breakeven", "max_bars",
        "pnl_tokyo", "pnl_london", "pnl_newyork",
        "trades_tokyo", "trades_london", "trades_newyork",
    ]
    save_cols = [c for c in output_cols if c in candidates.columns]
    cand_csv = os.path.join(ranked_dir, "rsi_structure_candidates.csv")
    candidates[save_cols].to_csv(cand_csv, index=False, encoding="utf-8-sig")
    print(f"  候補保存: {cand_csv}")

    if not candidates.empty:
        print(f"\n  --- 構造フィルタ候補 TOP20 ---")
        for i, (_, row) in enumerate(candidates.head(20).iterrows(), 1):
            filt_tags = []
            if row.get("has_htf"): filt_tags.append(f"HTF({row.get('htf_period',0)})")
            if row.get("has_bb_touch"): filt_tags.append("BB")
            if row.get("has_atr_low_vola"): filt_tags.append("LowVol")
            if row.get("has_wick_dir"): filt_tags.append(f"Wick({row.get('wick_ratio',0)})")
            tags = "+".join(filt_tags) if filt_tags else "none"
            print(f"    {i:2d}. {row['symbol']}_{row['timeframe']} [{row.get('session','?'):8s}]  PF={row['pf']:.3f}  WR={row['winrate']:.1f}%  DD={row['max_dd_pct']:.1f}%  trades={row['trade_count']}  [{tags}]")

    # Phase 4: GBPJPY_M5_london 別ランキング
    print(f"\n  Phase 4: GBPJPY_M5_london 別ランキング")
    gbp_london = df[
        (df["symbol"] == "GBPJPY")
        & (df["timeframe"] == "M5")
        & (df["session"] == "london")
    ].copy()

    if gbp_london.empty:
        print("    データなし")
    else:
        gbp_london["pf_capped"] = gbp_london["pf"].apply(_cap_pf)
        gbp_london = gbp_london.sort_values("pf_capped", ascending=False).reset_index(drop=True)

        # 統計 (trades >= 20)
        valid = gbp_london[gbp_london["trade_count"] >= 20]
        print(f"    テスト数: {len(gbp_london)} (trades≥20: {len(valid)})")
        if not valid.empty:
            print(f"    平均PF={valid['pf_capped'].mean():.3f}  中央PF={valid['pf_capped'].median():.3f}  最大PF={valid['pf_capped'].max():.3f}")
            print(f"    平均WR={valid['winrate'].mean():.1f}%  平均DD={valid['max_dd_pct'].mean():.1f}%")
            pf_ok = (valid["pf"] >= 1.15).sum()
            print(f"    PF≥1.15: {pf_ok}/{len(valid)} ({pf_ok/len(valid)*100:.1f}%)")

        print(f"\n    --- GBPJPY_M5_london TOP20 ---")
        for i, (_, row) in enumerate(gbp_london.head(20).iterrows(), 1):
            filt_tags = []
            if row.get("has_htf"): filt_tags.append(f"HTF({row.get('htf_period',0)})")
            if row.get("has_bb_touch"): filt_tags.append("BB")
            if row.get("has_atr_low_vola"): filt_tags.append("LowVol")
            if row.get("has_wick_dir"): filt_tags.append(f"Wick({row.get('wick_ratio',0)})")
            tags = "+".join(filt_tags) if filt_tags else "none"
            print(f"      {i:2d}. {row['strategy_name'][:30]:30s}  PF={row['pf_capped']:.3f}  WR={row['winrate']:.1f}%  DD={row['max_dd_pct']:.1f}%  trades={row['trade_count']}  hold={row.get('avg_hold_min',0):.0f}m  [{tags}]")

        # GBPJPY_M5_london ランキングを別CSV保存
        gbp_csv = os.path.join(ranked_dir, "gbpjpy_m5_london_ranking.csv")
        gbp_save_cols = [c for c in output_cols if c in gbp_london.columns]
        gbp_london[gbp_save_cols].to_csv(gbp_csv, index=False, encoding="utf-8-sig")
        print(f"\n    ランキング保存: {gbp_csv}")

    # Phase 5: 分析サマリー
    print(f"\n{'='*70}")
    print(f"  構造フィルタ分析サマリー")
    print(f"{'='*70}")

    # trades >= 20 のデータのみで統計
    stat_df = df[df["trade_count"] >= 20].copy()
    stat_df["pf"] = stat_df["pf"].apply(_cap_pf)

    if stat_df.empty:
        print("  有効なデータなし")
    else:
        # --- 各フィルタ単体の効果 ---
        print(f"\n  --- 各構造フィルタの効果 (trades≥20) ---")
        for filt_col, filt_name in [
            ("has_htf", "① H1トレンド一致"),
            ("has_bb_touch", "② BB外側タッチ"),
            ("has_atr_low_vola", "③ ATR低ボラ"),
            ("has_wick_dir", "④ ヒゲ反転方向"),
        ]:
            if filt_col in stat_df.columns:
                grp = stat_df.groupby(filt_col).agg(
                    avg_pf=("pf", "mean"),
                    med_pf=("pf", "median"),
                    avg_wr=("winrate", "mean"),
                    avg_trades=("trade_count", "mean"),
                    count=("pf", "count"),
                ).sort_index()
                for idx, row in grp.iterrows():
                    label = "あり" if idx else "なし"
                    print(f"    {filt_name} {label:3s}  avgPF={row['avg_pf']:.3f}  medPF={row['med_pf']:.3f}  WR={row['avg_wr']:.1f}%  trades={row['avg_trades']:.0f}  (n={row['count']})")

        # --- フィルタ数別 ---
        print(f"\n  --- 構造フィルタ数別 ---")
        n_grp = stat_df.groupby("n_struct_filters").agg(
            avg_pf=("pf", "mean"),
            med_pf=("pf", "median"),
            avg_trades=("trade_count", "mean"),
            count=("pf", "count"),
        )
        for idx, row in n_grp.iterrows():
            print(f"    {idx}個  avgPF={row['avg_pf']:.3f}  medPF={row['med_pf']:.3f}  trades={row['avg_trades']:.0f}  (n={row['count']})")

        # --- 通貨 × セッション別 ---
        print(f"\n  --- 通貨 × セッション別 ---")
        ps_grp = stat_df.groupby(["symbol", "session"]).agg(
            avg_pf=("pf", "mean"),
            med_pf=("pf", "median"),
            max_pf=("pf", "max"),
            avg_wr=("winrate", "mean"),
            avg_trades=("trade_count", "mean"),
            count=("pf", "count"),
            pf_ge_115=("pf", lambda x: (x >= 1.15).sum()),
        ).sort_values("avg_pf", ascending=False)
        for (sym, sess), row in ps_grp.iterrows():
            print(f"    {sym}_{TARGET_TIMEFRAME} [{sess:8s}]  avgPF={row['avg_pf']:.3f}  medPF={row['med_pf']:.3f}  maxPF={row['max_pf']:.3f}  WR={row['avg_wr']:.1f}%  PF≥1.15={row['pf_ge_115']}")

        # --- 最良フィルタ組み合わせ ---
        print(f"\n  --- 最良フィルタ組み合わせ TOP10 ---")
        stat_df["combo"] = (
            stat_df["has_htf"].map({True: "HTF", False: ""})
            + "+" + stat_df["has_bb_touch"].map({True: "BB", False: ""})
            + "+" + stat_df["has_atr_low_vola"].map({True: "LowVol", False: ""})
            + "+" + stat_df["has_wick_dir"].map({True: "Wick", False: ""})
        ).str.strip("+").str.replace(r"\++", "+", regex=True).str.strip("+")
        combo_grp = stat_df.groupby("combo").agg(
            avg_pf=("pf", "mean"),
            med_pf=("pf", "median"),
            avg_trades=("trade_count", "mean"),
            count=("pf", "count"),
            pf_ge_115=("pf", lambda x: (x >= 1.15).sum()),
        ).sort_values("avg_pf", ascending=False).head(10)
        for idx, row in combo_grp.iterrows():
            print(f"    {idx:30s}  avgPF={row['avg_pf']:.3f}  medPF={row['med_pf']:.3f}  trades={row['avg_trades']:.0f}  PF≥1.15={row['pf_ge_115']}  (n={row['count']})")

    # サマリー保存
    summary_path = os.path.join(results_dir, "rsi_structure_summary.txt")
    # 全出力をキャプチャするのではなく、簡易まとめをファイルに保存
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(f"RSI逆張り + 構造フィルタ探索結果\n")
        f.write(f"{'='*50}\n")
        f.write(f"RSI設定: RSI({RSI_PERIOD}), 閾値 {OVERSOLD}/{OVERBOUGHT}\n")
        f.write(f"対象: {', '.join(TARGET_SYMBOLS)} × {TARGET_TIMEFRAME}\n")
        f.write(f"セッション: {', '.join(TARGET_SESSIONS)}\n")
        f.write(f"戦略数: {len(configs)}\n")
        f.write(f"テスト数: {len(all_results)}\n")
        f.write(f"候補数 (PF≥{EVAL_MIN_PF}, DD≤{EVAL_MAX_DD}%, trades≥{EVAL_MIN_TRADES}): {len(candidates)}\n")
    print(f"\n  サマリー保存: {summary_path}")


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_dir)

    import yaml
    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler("logs/rsi_structure.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    config_path = os.path.join("config", "settings.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        settings = yaml.safe_load(f)

    run_structure_exploration(settings)
