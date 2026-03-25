"""RSI逆張り系 深掘り探索エンジン

EMAクロス系を除外し、RSI reversal / mean_reversion 系の派生戦略を
大量生成・バックテストし、exploration基準で候補を抽出する。

exploration基準:
  - OOS PF >= 1.00
  - MaxDD <= 20%
  - 取引回数 >= 300
"""

import os
import sys
import itertools
import hashlib
import json
import logging
from datetime import datetime

import pandas as pd
import numpy as np
from tqdm import tqdm

from engine.strategy_generator import write_strategy_file, _make_name
from engine.strategy_loader import load_all_strategies
from engine.configurable_strategy import ConfigurableStrategy
from data_loader import load_ohlc, discover_data_files
from metrics import evaluate_strategy
from engine.evolution import split_is_oos, _classify_session

logger = logging.getLogger(__name__)


# ================================================================
# パラメータグリッド定義
# ================================================================

# RSI期間
RSI_PERIODS = [7, 10, 14, 18, 21]

# エントリー閾値 (oversold, overbought)
ENTRY_THRESHOLDS = [
    (20, 80),
    (25, 75),
    (28, 72),
    (30, 70),
    (32, 68),
    (35, 65),
]

# 利確方法
TP_CONFIGS = [
    {"tp_type": "fixed", "tp_pips": 0.15},
    {"tp_type": "fixed", "tp_pips": 0.3},
    {"tp_type": "fixed", "tp_pips": 0.5},
    {"tp_type": "atr_mult", "tp_atr_mult": 1.5},
    {"tp_type": "atr_mult", "tp_atr_mult": 2.5},
    {"tp_type": "atr_mult", "tp_atr_mult": 3.5},
]

# 損切方法
SL_CONFIGS = [
    {"sl_type": "fixed", "sl_pips": 0.1},
    {"sl_type": "fixed", "sl_pips": 0.2},
    {"sl_type": "fixed", "sl_pips": 0.35},
    {"sl_type": "atr_mult", "sl_atr_mult": 1.0},
    {"sl_type": "atr_mult", "sl_atr_mult": 1.5},
    {"sl_type": "atr_mult", "sl_atr_mult": 2.5},
]

# 建値移動オプション
BREAKEVEN_OPTIONS = [
    {},  # なし
    {"breakeven": True, "be_trigger_pips": 0.15},
    {"breakeven": True, "be_trigger_pips": 0.3},
]

# 時間切れ決済
MAX_BARS_OPTIONS = [
    {},  # なし
    {"max_bars": 60},
    {"max_bars": 120},
    {"max_bars": 240},
]

# セッションフィルタ
SESSION_FILTERS = [
    [],  # フィルタなし
    [{"type": "session_filter", "session": "tokyo"}],
    [{"type": "session_filter", "session": "london"}],
    [{"type": "session_filter", "session": "newyork"}],
    [{"type": "session_filter", "session": "london_ny"}],
]

# 上位足フィルタ
HTF_FILTERS = [
    [],  # なし
    [{"type": "htf_trend", "period": 50}],
    [{"type": "htf_trend", "period": 100}],
]

# ボラフィルタ
VOLA_FILTERS = [
    [],  # なし
    [{"type": "atr_filter", "min_atr": 0.02, "max_atr": 0.5}],
    [{"type": "atr_filter", "min_atr": 0.05, "max_atr": 1.0}],
]

# ATR期間
ATR_PERIODS = [10, 14, 18]


def _generate_rsi_configs(target_count: int = 120) -> list[dict]:
    """RSI逆張り系の派生戦略を体系的に大量生成

    パラメータ空間が巨大なので、段階的にサンプリング:
    1. コアパラメータ (RSI期間 x 閾値 x TP x SL) の全組み合わせから均等サンプリング
    2. 各サンプルにランダムでオプション (建値/時間切れ/フィルタ) を付与
    """
    import random
    random.seed(42)

    configs = []
    seen_hashes = set()

    # Phase 1: コア組み合わせを生成
    core_combos = list(itertools.product(
        RSI_PERIODS,
        ENTRY_THRESHOLDS,
        TP_CONFIGS,
        SL_CONFIGS,
        ATR_PERIODS,
    ))
    random.shuffle(core_combos)

    # Phase 2: 各コア組み合わせにオプションを付けて生成
    combo_idx = 0
    attempts = 0
    max_attempts = target_count * 10

    while len(configs) < target_count and attempts < max_attempts:
        if combo_idx >= len(core_combos):
            combo_idx = 0
            random.shuffle(core_combos)

        rsi_period, (oversold, overbought), tp_cfg, sl_cfg, atr_period = core_combos[combo_idx]
        combo_idx += 1
        attempts += 1

        # ランダムにオプションを選択
        be_opt = random.choice(BREAKEVEN_OPTIONS)
        mb_opt = random.choice(MAX_BARS_OPTIONS)
        sess_filt = random.choice(SESSION_FILTERS)
        htf_filt = random.choice(HTF_FILTERS)
        vola_filt = random.choice(VOLA_FILTERS)

        # フィルターを結合 (最大2個まで)
        all_filters = sess_filt + htf_filt + vola_filt
        if len(all_filters) > 2:
            all_filters = random.sample(all_filters, 2)

        exit_rules = {
            **tp_cfg,
            **sl_cfg,
            "atr_period": atr_period,
            **be_opt,
            **mb_opt,
        }

        config = {
            "entry_signal": {
                "type": "rsi_reversal",
                "category": "mean_reversion",
                "period": rsi_period,
                "oversold": oversold,
                "overbought": overbought,
            },
            "entry_filters": all_filters,
            "exit_rules": exit_rules,
        }

        config["name"] = _make_name(config)

        # 重複チェック
        cfg_hash = hashlib.md5(
            json.dumps(config, sort_keys=True, default=str).encode()
        ).hexdigest()

        if cfg_hash not in seen_hashes:
            seen_hashes.add(cfg_hash)
            configs.append(config)

    logger.info(f"RSI逆張り派生戦略を {len(configs)} 個生成")
    return configs


def _run_oos_backtest(
    configs: list[dict],
    data_files: list[dict],
    initial_balance: float,
    spread: float,
    commission: float,
    is_ratio: float = 0.7,
) -> list[dict]:
    """全configに対してOOSバックテストを実行し、個別結果を返す"""
    results = []
    total = len(configs) * len(data_files)

    with tqdm(total=total, desc="  OOSバックテスト") as pbar:
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
                    result["category"] = "mean_reversion"
                    result["rsi_period"] = cfg["entry_signal"]["period"]
                    result["oversold"] = cfg["entry_signal"]["oversold"]
                    result["overbought"] = cfg["entry_signal"]["overbought"]
                    result["tp_type"] = cfg["exit_rules"].get("tp_type", "?")
                    result["sl_type"] = cfg["exit_rules"].get("sl_type", "?")

                    # セッションフィルタ名
                    filters = cfg.get("entry_filters", [])
                    sess_name = "all"
                    for f in filters:
                        if f.get("type") == "session_filter":
                            sess_name = f.get("session", "all")
                    result["session_filter"] = sess_name

                    # HTFフィルタ
                    has_htf = any(f.get("type") == "htf_trend" for f in filters)
                    result["has_htf_filter"] = has_htf

                    # ボラフィルタ
                    has_vola = any(f.get("type") == "atr_filter" for f in filters)
                    result["has_vola_filter"] = has_vola

                    # 建値/時間切れ
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


def _filter_exploration_candidates(
    results: list[dict],
    min_pf: float = 1.00,
    max_dd_pct: float = 20.0,
    min_trades: int = 300,
) -> pd.DataFrame:
    """exploration基準でフィルタリング

    基準: 同一戦略の全symbol×timeframe結果を集約してから判定
    """
    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results)

    # 戦略×通貨×時間足ごとの個別結果をそのまま使う
    # infを除外し、有限値のみ
    finite_mask = np.isfinite(df["pf"])
    candidates = df[
        finite_mask
        & (df["pf"] >= min_pf)
        & (df["max_dd_pct"] <= max_dd_pct)
        & (df["trade_count"] >= min_trades)
    ].copy()

    candidates = candidates.sort_values("pf", ascending=False).reset_index(drop=True)
    return candidates


def _make_comparison_table(
    results: list[dict],
    targets: list[tuple[str, str]],
) -> pd.DataFrame:
    """特定の通貨ペア×時間足の比較テーブルを作成"""
    df = pd.DataFrame(results)
    if df.empty:
        return df

    # 対象のみ抽出
    mask = pd.Series(False, index=df.index)
    for symbol, tf in targets:
        mask |= (df["symbol"] == symbol) & (df["timeframe"] == tf)
    subset = df[mask].copy()

    if subset.empty:
        return subset

    # 戦略 × (symbol_timeframe) ピボット
    subset["pair_tf"] = subset["symbol"] + "_" + subset["timeframe"]
    return subset


def _cap_pf(pf_val: float, cap: float = 10.0) -> float:
    """PFをキャップ (inf対策)"""
    if pf_val == float("inf") or pf_val != pf_val:  # inf or nan
        return cap
    return min(pf_val, cap)


def _summarize_findings(
    all_results: list[dict],
    candidates: pd.DataFrame,
    comparison: pd.DataFrame,
) -> str:
    """分析結果を文章でまとめる"""
    df = pd.DataFrame(all_results)
    # PFをキャップ (inf/nan対策, 少数トレードで歪むため)
    df["pf"] = df["pf"].apply(_cap_pf)
    lines = []
    lines.append("\n" + "=" * 70)
    lines.append("  RSI逆張り深掘り探索 - 分析サマリー")
    lines.append("=" * 70)

    # 全体統計
    total_combos = len(df)
    lines.append(f"\n  テスト総数: {total_combos} (戦略 × 通貨 × 時間足)")
    lines.append(f"  exploration候補数: {len(candidates)}")

    if df.empty:
        lines.append("\n  結果なし")
        return "\n".join(lines)

    # --- カテゴリ別 (session_filter) ---
    lines.append("\n  --- セッションフィルタ別 平均PF ---")
    sess_group = df.groupby("session_filter").agg(
        avg_pf=("pf", "mean"),
        avg_wr=("winrate", "mean"),
        avg_trades=("trade_count", "mean"),
        count=("pf", "count"),
    ).sort_values("avg_pf", ascending=False)
    for idx, row in sess_group.iterrows():
        lines.append(f"    {idx:15s}  PF={row['avg_pf']:.3f}  WR={row['avg_wr']:.1f}%  trades={row['avg_trades']:.0f}  (n={row['count']})")

    # --- 通貨ペア × 時間足別 ---
    lines.append("\n  --- 通貨ペア × 時間足別 平均PF ---")
    pair_tf = df.copy()
    pair_tf["pair_tf"] = pair_tf["symbol"] + "_" + pair_tf["timeframe"]
    pt_group = pair_tf.groupby("pair_tf").agg(
        avg_pf=("pf", "mean"),
        avg_wr=("winrate", "mean"),
        avg_dd=("max_dd_pct", "mean"),
        avg_trades=("trade_count", "mean"),
        count=("pf", "count"),
    ).sort_values("avg_pf", ascending=False)
    for idx, row in pt_group.iterrows():
        lines.append(f"    {idx:15s}  PF={row['avg_pf']:.3f}  WR={row['avg_wr']:.1f}%  DD={row['avg_dd']:.1f}%  trades={row['avg_trades']:.0f}")

    # --- 通貨 × 時間足 × セッション で最もマシな組み合わせ ---
    lines.append("\n  --- 通貨 × 時間足 × セッション 最良組み合わせ TOP10 ---")
    trio = df.groupby(["symbol", "timeframe", "session_filter"]).agg(
        avg_pf=("pf", "mean"),
        max_pf=("pf", "max"),
        avg_wr=("winrate", "mean"),
        avg_trades=("trade_count", "mean"),
        candidates=("pf", lambda x: (x >= 1.0).sum()),
    ).sort_values("avg_pf", ascending=False).head(10)
    for (sym, tf, sess), row in trio.iterrows():
        lines.append(f"    {sym}_{tf} [{sess:12s}]  avgPF={row['avg_pf']:.3f}  maxPF={row['max_pf']:.3f}  WR={row['avg_wr']:.1f}%  PF≥1候補={row['candidates']}")

    # --- RSI期間別 ---
    lines.append("\n  --- RSI期間別 平均PF ---")
    rsi_group = df.groupby("rsi_period").agg(
        avg_pf=("pf", "mean"),
        avg_wr=("winrate", "mean"),
    ).sort_values("avg_pf", ascending=False)
    for idx, row in rsi_group.iterrows():
        lines.append(f"    RSI({idx:2d})  PF={row['avg_pf']:.3f}  WR={row['avg_wr']:.1f}%")

    # --- 閾値別 ---
    lines.append("\n  --- RSI閾値別 平均PF ---")
    df["threshold"] = df["oversold"].astype(str) + "/" + df["overbought"].astype(str)
    th_group = df.groupby("threshold").agg(
        avg_pf=("pf", "mean"),
        avg_wr=("winrate", "mean"),
    ).sort_values("avg_pf", ascending=False)
    for idx, row in th_group.iterrows():
        lines.append(f"    {idx:8s}  PF={row['avg_pf']:.3f}  WR={row['avg_wr']:.1f}%")

    # --- TP/SL方式別 ---
    lines.append("\n  --- TP方式別 平均PF ---")
    tp_group = df.groupby("tp_type").agg(avg_pf=("pf", "mean")).sort_values("avg_pf", ascending=False)
    for idx, row in tp_group.iterrows():
        lines.append(f"    {idx:10s}  PF={row['avg_pf']:.3f}")

    lines.append("\n  --- SL方式別 平均PF ---")
    sl_group = df.groupby("sl_type").agg(avg_pf=("pf", "mean")).sort_values("avg_pf", ascending=False)
    for idx, row in sl_group.iterrows():
        lines.append(f"    {idx:10s}  PF={row['avg_pf']:.3f}")

    # --- 建値移動あり/なし ---
    lines.append("\n  --- 建値移動の効果 ---")
    be_group = df.groupby("has_breakeven").agg(avg_pf=("pf", "mean"), avg_wr=("winrate", "mean"))
    for idx, row in be_group.iterrows():
        label = "あり" if idx else "なし"
        lines.append(f"    建値移動{label}  PF={row['avg_pf']:.3f}  WR={row['avg_wr']:.1f}%")

    # --- 上位足フィルタあり/なし ---
    lines.append("\n  --- 上位足フィルタの効果 ---")
    htf_group = df.groupby("has_htf_filter").agg(avg_pf=("pf", "mean"), avg_trades=("trade_count", "mean"))
    for idx, row in htf_group.iterrows():
        label = "あり" if idx else "なし"
        lines.append(f"    HTFフィルタ{label}  PF={row['avg_pf']:.3f}  trades={row['avg_trades']:.0f}")

    # --- 結論 ---
    lines.append("\n" + "=" * 70)
    lines.append("  結論と次の方針")
    lines.append("=" * 70)

    # 最良の通貨×時間足×セッション
    if not trio.empty:
        best_trio = trio.index[0]
        best_pf = trio.iloc[0]["avg_pf"]
        lines.append(f"\n  1. 最もマシな組み合わせ: {best_trio[0]}_{best_trio[1]} [{best_trio[2]}]  avgPF={best_pf:.3f}")

    # 最良のRSI期間
    if not rsi_group.empty:
        best_rsi = rsi_group.index[0]
        lines.append(f"  2. 最良RSI期間: RSI({best_rsi})")

    # 最良の閾値
    if not th_group.empty:
        best_th = th_group.index[0]
        lines.append(f"  3. 最良RSI閾値: {best_th}")

    # 候補数で判断
    if len(candidates) == 0:
        lines.append("\n  [警告] exploration基準 (PF≥1.0, DD≤20%, trades≥300) を満たす戦略は0個。")
        lines.append("  → RSI逆張り単体ではスプレッドを超えるのが困難。")
        lines.append("  → 次の方針: BB反発・ヒゲ反転との複合シグナル、またはフィルタ強化を検討。")
    elif len(candidates) < 10:
        lines.append(f"\n  exploration候補は {len(candidates)} 個（少数）。")
        lines.append("  → 有望な狭いパラメータ帯に集中し、さらにフィルタを精緻化する。")
    else:
        lines.append(f"\n  exploration候補は {len(candidates)} 個。")
        lines.append("  → 候補群の共通パラメータを分析し、次世代の遺伝的探索に投入する。")

    # 次に集中すべき型
    lines.append("\n  次に集中すべき型:")
    lines.append("    a) RSI逆張り + セッションフィルタ付き (特にロンドン/NY)")
    lines.append("    b) RSI逆張り + 上位足トレンド一致フィルタ")
    lines.append("    c) BB反発 / ヒゲ反転 系の同様の深掘り探索")
    lines.append("")

    return "\n".join(lines)


# ================================================================
# メイン実行
# ================================================================

def run_exploration(settings: dict) -> None:
    """RSI逆張り深掘り探索のメイン実行"""
    initial_balance = settings.get("initial_balance", 100000)
    spread = settings.get("spread", 0.02)
    commission = settings.get("commission", 0.005)
    data_dir = settings.get("data_dir", "data/raw")
    results_dir = settings.get("results_dir", "results")
    is_ratio = settings.get("research", {}).get("is_ratio", 0.7)

    ranked_dir = os.path.join(results_dir, "ranked")
    os.makedirs(ranked_dir, exist_ok=True)

    # データ検出
    data_files = discover_data_files(data_dir)
    if not data_files:
        logger.error(f"データファイルが見つかりません: {data_dir}")
        return

    print(f"\n{'='*70}")
    print(f"  RSI逆張り深掘り探索")
    print(f"{'='*70}")
    print(f"  データファイル: {len(data_files)}")
    for d in data_files:
        print(f"    - {d['symbol']}_{d['timeframe']}")

    # Phase 1: 戦略生成
    print(f"\n  Phase 1: RSI逆張り派生戦略の大量生成...")
    configs = _generate_rsi_configs(target_count=120)
    print(f"  生成数: {len(configs)} 個")

    # パラメータ分布を表示
    periods = [c["entry_signal"]["period"] for c in configs]
    thresholds = [(c["entry_signal"]["oversold"], c["entry_signal"]["overbought"]) for c in configs]
    sessions = []
    for c in configs:
        s = "all"
        for f in c.get("entry_filters", []):
            if f.get("type") == "session_filter":
                s = f.get("session", "all")
        sessions.append(s)

    from collections import Counter
    print(f"  RSI期間分布: {dict(Counter(periods))}")
    print(f"  セッション分布: {dict(Counter(sessions))}")

    # Phase 2: OOSバックテスト
    print(f"\n  Phase 2: OOSバックテスト ({len(configs)} × {len(data_files)} = {len(configs)*len(data_files)} テスト)")
    all_results = _run_oos_backtest(
        configs, data_files, initial_balance, spread, commission, is_ratio=is_ratio,
    )
    print(f"  結果数: {len(all_results)}")

    if not all_results:
        print("  結果がありません。終了。")
        return

    # 全結果を保存
    all_df = pd.DataFrame(all_results)
    all_csv = os.path.join(results_dir, "rsi_exploration_all.csv")
    all_df.to_csv(all_csv, index=False, encoding="utf-8-sig")
    print(f"  全結果保存: {all_csv}")

    # Phase 3: exploration基準でフィルタリング
    print(f"\n  Phase 3: Exploration基準でフィルタリング")
    print(f"    基準: OOS PF >= 1.00, MaxDD <= 20%, trades >= 300")
    candidates = _filter_exploration_candidates(
        all_results, min_pf=1.00, max_dd_pct=20.0, min_trades=300,
    )
    print(f"  候補数: {len(candidates)}")

    # 候補を保存
    candidates_csv = os.path.join(ranked_dir, "exploration_candidates.csv")
    output_cols = [
        "strategy_name", "symbol", "timeframe", "session_filter",
        "pf", "winrate", "max_dd_pct", "trade_count", "avg_hold_min",
        "total_pnl", "expectancy", "payoff_ratio",
        "max_consecutive_losses",
        "rsi_period", "oversold", "overbought",
        "tp_type", "sl_type",
        "has_breakeven", "max_bars",
        "has_htf_filter", "has_vola_filter",
        "pnl_tokyo", "pnl_london", "pnl_newyork",
        "trades_tokyo", "trades_london", "trades_newyork",
    ]
    save_cols = [c for c in output_cols if c in candidates.columns]
    candidates[save_cols].to_csv(candidates_csv, index=False, encoding="utf-8-sig")
    print(f"  候補保存: {candidates_csv}")

    if not candidates.empty:
        print(f"\n  --- Exploration候補 TOP20 ---")
        for i, (_, row) in enumerate(candidates.head(20).iterrows(), 1):
            print(f"    {i:2d}. {row['strategy_name'][:35]:35s}  {row['symbol']}_{row['timeframe']}  [{row.get('session_filter','all'):10s}]  PF={row['pf']:.3f}  WR={row['winrate']:.1f}%  DD={row['max_dd_pct']:.1f}%  trades={row['trade_count']}")

    # Phase 4: 個別比較 (USDJPY M1, USDJPY M5, EURJPY M1, GBPJPY M1)
    print(f"\n  Phase 4: 個別比較")
    targets = [
        ("USDJPY", "M1"),
        ("USDJPY", "M5"),
        ("EURJPY", "M1"),
        ("GBPJPY", "M1"),
    ]
    comparison = _make_comparison_table(all_results, targets)

    if not comparison.empty:
        # PFキャップ処理
        comparison["pf_capped"] = comparison["pf"].apply(lambda x: _cap_pf(x, 10.0))

        # 各ターゲットの統計 (trades >= 20 で統計を取る)
        for sym, tf in targets:
            subset = comparison[(comparison["symbol"] == sym) & (comparison["timeframe"] == tf)]
            if subset.empty:
                print(f"\n    {sym}_{tf}: データなし")
                continue
            # 統計は一定トレード数以上で計算
            stat_sub = subset[subset["trade_count"] >= 20]
            print(f"\n    {sym}_{tf}: {len(subset)} テスト (trades≥20: {len(stat_sub)})")
            if not stat_sub.empty:
                print(f"      平均PF={stat_sub['pf_capped'].mean():.3f}  最大PF={stat_sub['pf_capped'].max():.3f}  中央PF={stat_sub['pf_capped'].median():.3f}")
                print(f"      平均WR={stat_sub['winrate'].mean():.1f}%  平均DD={stat_sub['max_dd_pct'].mean():.1f}%")
                print(f"      平均trades={stat_sub['trade_count'].mean():.0f}")
            # PF >= 1.0 の割合 (全体)
            pf_ok = ((subset["pf"] >= 1.0) & (subset["trade_count"] >= 20)).sum()
            total_valid = (subset["trade_count"] >= 20).sum()
            print(f"      PF≥1.0 (trades≥20): {pf_ok}/{total_valid} ({pf_ok/max(total_valid,1)*100:.1f}%)")

            # そのペアの候補TOP5 (trades >= 20)
            top5 = stat_sub.sort_values("pf_capped", ascending=False).head(5)
            for _, row in top5.iterrows():
                print(f"        {row['strategy_name'][:30]:30s}  PF={row['pf_capped']:.3f}  WR={row['winrate']:.1f}%  DD={row['max_dd_pct']:.1f}%  trades={row['trade_count']}")

        # 比較結果を保存
        comp_csv = os.path.join(results_dir, "rsi_comparison_targets.csv")
        comparison.to_csv(comp_csv, index=False, encoding="utf-8-sig")
        print(f"\n  比較結果保存: {comp_csv}")

    # Phase 5: 通貨ペア×時間足×セッション別ブレイクダウン保存
    breakdown_csv = os.path.join(results_dir, "rsi_breakdown_detail.csv")
    breakdown_df = pd.DataFrame(all_results)
    if not breakdown_df.empty:
        breakdown_agg = breakdown_df.groupby(["symbol", "timeframe", "session_filter"]).agg(
            avg_pf=("pf", "mean"),
            max_pf=("pf", "max"),
            avg_winrate=("winrate", "mean"),
            avg_max_dd=("max_dd_pct", "mean"),
            avg_trades=("trade_count", "mean"),
            total_tests=("pf", "count"),
            pf_ge_1=("pf", lambda x: (x >= 1.0).sum()),
        ).reset_index()
        breakdown_agg["pf_ge_1_pct"] = (breakdown_agg["pf_ge_1"] / breakdown_agg["total_tests"] * 100).round(1)
        breakdown_agg = breakdown_agg.sort_values("avg_pf", ascending=False)
        breakdown_agg.to_csv(breakdown_csv, index=False, encoding="utf-8-sig")
        print(f"  ブレイクダウン保存: {breakdown_csv}")

    # Phase 6: 総合分析
    summary = _summarize_findings(all_results, candidates, comparison)
    print(summary)

    # サマリーをファイルにも保存
    summary_path = os.path.join(results_dir, "rsi_exploration_summary.txt")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(summary)
    print(f"  サマリー保存: {summary_path}")


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_dir)

    import yaml
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler("logs/rsi_exploration.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    os.makedirs("logs", exist_ok=True)

    config_path = os.path.join("config", "settings.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        settings = yaml.safe_load(f)

    run_exploration(settings)
