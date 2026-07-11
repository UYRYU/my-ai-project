"""進化ループエンジン (v2)

IS/OOS分割・walk-forwardテスト・spread感応度・頑健性テスト・カテゴリ多様性を備えた
本格的な戦略探索エンジン。
"""

import os
import shutil
import logging
import json
from datetime import datetime

import pandas as pd
import numpy as np

from engine.strategy_generator import (
    generate_and_write, write_strategy_file, generate_many,
    get_category_distribution, SIGNAL_CATEGORIES,
)
from engine.strategy_mutator import generate_next_generation, analyze_top_features
from engine.strategy_loader import load_all_strategies, extract_all_configs
from data_loader import load_ohlc, discover_data_files
from metrics import evaluate_strategy, spread_sensitivity_test, calculate_spread_robustness
from report import (
    create_ranking, save_ranking, save_all_results, print_summary,
    save_oos_ranking, save_robustness_report, save_detail_breakdown,
)

from tqdm import tqdm

logger = logging.getLogger(__name__)


# ================================================================
# データ分割
# ================================================================

def split_is_oos(df: pd.DataFrame, is_ratio: float = 0.7) -> tuple[pd.DataFrame, pd.DataFrame]:
    """In-Sample / Out-of-Sample に時系列分割"""
    n = len(df)
    split_idx = int(n * is_ratio)
    is_df = df.iloc[:split_idx].reset_index(drop=True)
    oos_df = df.iloc[split_idx:].reset_index(drop=True)
    return is_df, oos_df


def split_walk_forward(
    df: pd.DataFrame,
    n_windows: int = 3,
    is_ratio: float = 0.7,
) -> list[tuple[pd.DataFrame, pd.DataFrame]]:
    """Walk-Forward分割: 重複するIS/OOS窓を複数生成

    各窓のIS期間で最適化し、OOS期間で検証するための分割。
    """
    n = len(df)
    window_size = n // n_windows
    if window_size < 200:
        # データ不足時はフォールバック
        return [split_is_oos(df, is_ratio)]

    windows = []
    for i in range(n_windows):
        start = i * (window_size // 2)  # 50%オーバーラップ
        end = min(start + window_size, n)
        if end - start < 100:
            continue
        window_df = df.iloc[start:end].reset_index(drop=True)
        is_df, oos_df = split_is_oos(window_df, is_ratio)
        if len(is_df) > 50 and len(oos_df) > 20:
            windows.append((is_df, oos_df))

    if not windows:
        return [split_is_oos(df, is_ratio)]

    return windows


# ================================================================
# ヘルパー
# ================================================================

def _clear_directory(dirpath: str) -> None:
    """ディレクトリ内のPythonファイルと__pycache__をクリア"""
    if not os.path.isdir(dirpath):
        return
    for item in os.listdir(dirpath):
        if item.startswith("_"):
            continue
        path = os.path.join(dirpath, item)
        if item.endswith(".py"):
            os.remove(path)
        elif item == "__pycache__" and os.path.isdir(path):
            shutil.rmtree(path)


def _classify_session(hour: int) -> str:
    """時間からセッション名を返す"""
    if 0 <= hour < 9:
        return "tokyo"
    elif 9 <= hour < 16:
        return "london"
    else:
        return "newyork"


def _run_backtest_batch(
    strategy_classes: list,
    data_files: list[dict],
    initial_balance: float,
    spread: float,
    commission: float,
    data_override: dict | None = None,
    label: str = "IS",
) -> list[dict]:
    """全データ x 全戦略のバックテスト実行

    data_override: {(symbol, timeframe): DataFrame} ISまたはOOS用の分割データ
    """
    results = []
    total = len(data_files) * len(strategy_classes)

    with tqdm(total=total, desc=f"  {label}バックテスト", leave=False) as pbar:
        for data_info in data_files:
            symbol = data_info["symbol"]
            timeframe = data_info["timeframe"]

            try:
                if data_override and (symbol, timeframe) in data_override:
                    df = data_override[(symbol, timeframe)]
                else:
                    df = load_ohlc(data_info["filepath"])
            except Exception as e:
                logger.error(f"データ読み込み失敗: {e}")
                pbar.update(len(strategy_classes))
                continue

            for cls in strategy_classes:
                try:
                    strat = cls(spread=spread, commission=commission)
                    trades = strat.backtest(df, initial_balance=initial_balance)
                    result = evaluate_strategy(trades, initial_balance)
                    result["strategy_name"] = strat.name
                    result["symbol"] = symbol
                    result["timeframe"] = timeframe
                    result["category"] = strat.config.get("entry_signal", {}).get("category", "unknown")

                    # 時間帯別成績
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
                    logger.error(f"バックテスト失敗 ({cls.name if hasattr(cls, 'name') else '?'}, {symbol}_{timeframe}): {e}")
                finally:
                    pbar.update(1)

    return results


def _aggregate_by_strategy(results: list[dict]) -> list[dict]:
    """戦略名ごとに全通貨ペア・時間足の結果を集約"""
    if not results:
        return []

    df = pd.DataFrame(results)
    agg = df.groupby("strategy_name").agg(
        pf=("pf", "mean"),
        winrate=("winrate", "mean"),
        max_dd_pct=("max_dd_pct", "max"),
        total_pnl=("total_pnl", "sum"),
        avg_holding_seconds=("avg_holding_seconds", "mean"),
        trade_count=("trade_count", "sum"),
        max_consecutive_losses=("max_consecutive_losses", "max"),
        expectancy=("expectancy", "mean"),
        payoff_ratio=("payoff_ratio", "mean"),
        pnl_tokyo=("pnl_tokyo", "sum"),
        pnl_london=("pnl_london", "sum"),
        pnl_newyork=("pnl_newyork", "sum"),
        category=("category", "first"),
    ).reset_index()

    return agg.to_dict("records")


def _select_top_k(results: list[dict], top_k: int, min_pf: float, min_trades: int) -> list[dict]:
    """上位K戦略を選出（カテゴリ多様性を考慮）"""
    qualified = [
        r for r in results
        if r.get("pf", 0) >= min_pf and r.get("trade_count", 0) >= min_trades
    ]
    qualified.sort(key=lambda x: x.get("pf", 0), reverse=True)

    if len(qualified) < top_k:
        fallback = [r for r in results if r.get("trade_count", 0) > 0]
        fallback.sort(key=lambda x: x.get("pf", 0), reverse=True)
        qualified = fallback

    # カテゴリ多様性: 各カテゴリから最低1つは選出
    selected = []
    selected_names = set()
    categories = list(SIGNAL_CATEGORIES.keys())

    # まず各カテゴリから最良を1つずつ
    for cat in categories:
        cat_results = [r for r in qualified if r.get("category") == cat and r["strategy_name"] not in selected_names]
        if cat_results:
            best = cat_results[0]
            selected.append(best)
            selected_names.add(best["strategy_name"])

    # 残りをPF順で埋める
    for r in qualified:
        if len(selected) >= top_k:
            break
        if r["strategy_name"] not in selected_names:
            selected.append(r)
            selected_names.add(r["strategy_name"])

    return selected[:top_k]


def _approve_strategies(
    results: list[dict],
    generated_dir: str,
    approved_dir: str,
    approved_pf: float,
    approved_max_dd: float,
    min_trades: int,
) -> list[str]:
    """承認条件を満たす戦略をapprovedにコピー"""
    os.makedirs(approved_dir, exist_ok=True)
    approved = []

    for r in results:
        name = r.get("strategy_name", "")
        pf = r.get("pf", 0)
        dd = r.get("max_dd_pct", 100)
        trades = r.get("trade_count", 0)

        if pf >= approved_pf and dd <= (approved_max_dd * 100) and trades >= min_trades:
            src = os.path.join(generated_dir, f"{name}.py")
            dst = os.path.join(approved_dir, f"{name}.py")
            if os.path.isfile(src) and not os.path.isfile(dst):
                shutil.copy2(src, dst)
                approved.append(name)
                logger.info(f"  承認: {name} (PF={pf:.2f}, DD={dd:.1f}%, trades={trades})")

    return approved


def _archive_strategies(generated_dir: str, archived_dir: str, approved_names: set) -> None:
    """未承認の戦略をarchivedに移動"""
    os.makedirs(archived_dir, exist_ok=True)
    if not os.path.isdir(generated_dir):
        return
    for filename in os.listdir(generated_dir):
        if not filename.endswith(".py") or filename.startswith("_"):
            continue
        name = filename.replace(".py", "")
        if name not in approved_names:
            src = os.path.join(generated_dir, filename)
            dst = os.path.join(archived_dir, filename)
            if not os.path.exists(dst):
                shutil.move(src, dst)


# ================================================================
# 頑健性テスト
# ================================================================

def _run_robustness_tests(
    strategy_classes: list,
    data_files: list[dict],
    initial_balance: float,
    spread: float,
    commission: float,
    top_names: set,
) -> list[dict]:
    """上位戦略に対して頑健性テストを実行

    テスト項目:
    1. Spread感応度 (1x, 1.5x, 2x, 3x)
    2. 各通貨ペアでの個別成績
    """
    robustness = []

    for cls in strategy_classes:
        if not hasattr(cls, "name") or cls.name not in top_names:
            continue

        strat = cls(spread=spread, commission=commission)
        spread_results_all = []

        for data_info in data_files:
            try:
                df = load_ohlc(data_info["filepath"])
                sens = spread_sensitivity_test(
                    strat, df, initial_balance,
                    spread_multipliers=[1.0, 1.5, 2.0, 3.0],
                )
                spread_results_all.extend(sens)
            except Exception:
                continue

        if not spread_results_all:
            continue

        spread_robustness = calculate_spread_robustness(spread_results_all)

        # 全spread倍率でのPF平均
        pf_by_mult = {}
        for r in spread_results_all:
            m = r["spread_mult"]
            pf_by_mult.setdefault(m, []).append(r["pf"])

        entry = {
            "strategy_name": strat.name,
            "category": strat.config.get("entry_signal", {}).get("category", "unknown"),
            "spread_robustness": round(spread_robustness, 4),
        }

        for m, pfs in sorted(pf_by_mult.items()):
            avg_pf = sum(pfs) / len(pfs) if pfs else 0
            entry[f"pf_spread_{m:.1f}x"] = round(avg_pf, 4)

        robustness.append(entry)

    return robustness


# ================================================================
# Walk-Forward テスト
# ================================================================

def _run_walk_forward(
    strategy_classes: list,
    data_files: list[dict],
    initial_balance: float,
    spread: float,
    commission: float,
    n_windows: int = 3,
    is_ratio: float = 0.7,
    top_names: set | None = None,
) -> list[dict]:
    """Walk-Forwardテスト: 複数窓でIS/OOSを検証"""
    wf_results = []

    for cls in strategy_classes:
        if top_names and (not hasattr(cls, "name") or cls.name not in top_names):
            continue

        strat_name = cls.name if hasattr(cls, "name") else "?"
        is_pfs = []
        oos_pfs = []
        oos_trades_total = 0
        oos_pnl_total = 0.0

        for data_info in data_files:
            try:
                df = load_ohlc(data_info["filepath"])
            except Exception:
                continue

            windows = split_walk_forward(df, n_windows=n_windows, is_ratio=is_ratio)

            for is_df, oos_df in windows:
                try:
                    strat = cls(spread=spread, commission=commission)
                    # IS
                    is_trades = strat.backtest(is_df, initial_balance=initial_balance)
                    is_metrics = evaluate_strategy(is_trades, initial_balance)
                    is_pfs.append(is_metrics["pf"])

                    # OOS
                    oos_trades = strat.backtest(oos_df, initial_balance=initial_balance)
                    oos_metrics = evaluate_strategy(oos_trades, initial_balance)
                    oos_pfs.append(oos_metrics["pf"])
                    oos_trades_total += oos_metrics["trade_count"]
                    oos_pnl_total += oos_metrics["total_pnl"]
                except Exception:
                    continue

        if is_pfs and oos_pfs:
            avg_is_pf = sum(is_pfs) / len(is_pfs)
            avg_oos_pf = sum(oos_pfs) / len(oos_pfs)
            # OOS/IS比率: 1.0に近いほど過学習していない
            oos_is_ratio = avg_oos_pf / avg_is_pf if avg_is_pf > 0 else 0.0
            wf_results.append({
                "strategy_name": strat_name,
                "is_pf_avg": round(avg_is_pf, 4),
                "oos_pf_avg": round(avg_oos_pf, 4),
                "oos_is_ratio": round(oos_is_ratio, 4),
                "oos_trade_count": oos_trades_total,
                "oos_total_pnl": round(oos_pnl_total, 2),
                "n_windows": len(is_pfs),
            })

    return wf_results


# ================================================================
# メイン進化ループ
# ================================================================

def run_evolution(settings: dict) -> None:
    """進化型研究ループのメイン実行 (v2)"""
    # 設定読み込み
    initial_balance = settings.get("initial_balance", 100000)
    spread = settings.get("spread", 0.2)
    commission = settings.get("commission", 0.01)
    data_dir = settings.get("data_dir", "data/raw")
    results_dir = settings.get("results_dir", "results")
    strategies_base = settings.get("strategies_dir_base", "strategies")

    research = settings.get("research", {})
    rounds = research.get("rounds", 5)
    strats_per_round = research.get("strategies_per_round", 50)
    top_k = research.get("top_k", 10)
    approved_pf = research.get("approved_pf", 1.35)
    approved_max_dd = research.get("approved_max_dd", 0.12)
    min_trades = research.get("min_trades", 100)
    is_ratio = research.get("is_ratio", 0.7)
    wf_windows = research.get("wf_windows", 3)

    ranking_filters = settings.get("ranking_filters", {})
    filter_min_pf = ranking_filters.get("min_pf", 1.2)
    filter_max_dd = ranking_filters.get("max_drawdown_pct", 15.0)
    filter_min_trades = ranking_filters.get("min_trades", 100)

    generated_dir = os.path.join(strategies_base, "generated")
    approved_dir = os.path.join(strategies_base, "approved")
    archived_dir = os.path.join(strategies_base, "archived")
    generations_dir = os.path.join(results_dir, "generations")
    best_dir = os.path.join(results_dir, "best")
    ranked_dir = os.path.join(results_dir, "ranked")

    for d in [generated_dir, approved_dir, archived_dir, generations_dir, best_dir, ranked_dir]:
        os.makedirs(d, exist_ok=True)

    # データファイル検出
    data_files = discover_data_files(data_dir)
    if not data_files:
        logger.error(f"データファイルが見つかりません: {data_dir}")
        return

    logger.info(f"データファイル: {len(data_files)}")
    logger.info(f"ラウンド数: {rounds}, 戦略/ラウンド: {strats_per_round}")

    # IS/OOS データ分割
    print("\n  データ分割 (IS/OOS)...")
    is_data = {}
    oos_data = {}
    for data_info in data_files:
        symbol = data_info["symbol"]
        timeframe = data_info["timeframe"]
        try:
            df = load_ohlc(data_info["filepath"])
            is_df, oos_df = split_is_oos(df, is_ratio=is_ratio)
            is_data[(symbol, timeframe)] = is_df
            oos_data[(symbol, timeframe)] = oos_df
            logger.info(f"  {symbol}_{timeframe}: IS={len(is_df)} rows, OOS={len(oos_df)} rows")
        except Exception as e:
            logger.error(f"データ分割失敗 ({symbol}_{timeframe}): {e}")

    all_approved = []
    all_oos_results = []
    all_robustness = []
    top_configs_for_next = []

    for gen in range(1, rounds + 1):
        print(f"\n{'='*70}")
        print(f"  ラウンド {gen}/{rounds}")
        print(f"{'='*70}")
        logger.info(f"=== ラウンド {gen}/{rounds} 開始 ===")

        # 戦略生成
        _clear_directory(generated_dir)

        if gen == 1 or not top_configs_for_next:
            logger.info(f"初回ランダム生成: {strats_per_round} 個")
            generate_and_write(strats_per_round, generated_dir, base_seed=gen * 1000)
        else:
            logger.info(f"進化生成 (親: {len(top_configs_for_next)} 戦略)")
            features = analyze_top_features(top_configs_for_next)
            logger.info(f"  上位シグナル分布: {features['signal_types']}")
            logger.info(f"  上位カテゴリ分布: {features.get('category_types', {})}")
            next_gen_configs = generate_next_generation(
                top_configs_for_next,
                count=strats_per_round,
                base_seed=gen * 1000,
            )
            # カテゴリ分布をログ出力
            cat_dist = get_category_distribution(next_gen_configs)
            logger.info(f"  生成カテゴリ分布: {cat_dist}")
            for cfg in next_gen_configs:
                write_strategy_file(cfg, generated_dir)

        # 戦略読み込み
        strategy_classes = load_all_strategies(generated_dir)
        if not strategy_classes:
            logger.warning("戦略の読み込みに失敗")
            continue

        logger.info(f"読み込んだ戦略数: {len(strategy_classes)}")

        # === Phase 1: In-Sample バックテスト ===
        print(f"\n  Phase 1: In-Sample テスト ({len(strategy_classes)} 戦略)")
        is_results = _run_backtest_batch(
            strategy_classes, data_files, initial_balance, spread, commission,
            data_override=is_data, label="IS",
        )

        if not is_results:
            logger.warning("ISバックテスト結果なし")
            continue

        # IS集約
        is_aggregated = _aggregate_by_strategy(is_results)

        # IS結果保存
        gen_filename = f"generation_{gen:03d}_is.csv"
        pd.DataFrame(is_results).to_csv(
            os.path.join(generations_dir, gen_filename), index=False, encoding="utf-8-sig"
        )

        # 上位K戦略を抽出
        top_strategies = _select_top_k(is_aggregated, top_k, filter_min_pf, filter_min_trades)
        top_names = {s["strategy_name"] for s in top_strategies}

        print(f"\n  IS上位 {len(top_strategies)} 戦略:")
        for i, s in enumerate(top_strategies, 1):
            cat = s.get('category', '?')[:8]
            print(f"    {i:2d}. [{cat:8s}] {s['strategy_name'][:35]:35s}  PF={s['pf']:.3f}  WR={s['winrate']:.1f}%  DD={s['max_dd_pct']:.1f}%  trades={s['trade_count']}  maxLoss={s.get('max_consecutive_losses', '?')}")

        # === Phase 2: Out-of-Sample バックテスト ===
        print(f"\n  Phase 2: Out-of-Sample テスト (上位 {len(top_names)} 戦略)")
        # 上位戦略のみでOOSテスト
        top_classes = [cls for cls in strategy_classes if hasattr(cls, "name") and cls.name in top_names]
        oos_results = _run_backtest_batch(
            top_classes, data_files, initial_balance, spread, commission,
            data_override=oos_data, label="OOS",
        )

        oos_aggregated = _aggregate_by_strategy(oos_results)

        # OOS結果保存
        oos_filename = f"generation_{gen:03d}_oos.csv"
        pd.DataFrame(oos_results).to_csv(
            os.path.join(generations_dir, oos_filename), index=False, encoding="utf-8-sig"
        )

        if oos_aggregated:
            print(f"\n  OOS結果:")
            oos_sorted = sorted(oos_aggregated, key=lambda x: x.get("pf", 0), reverse=True)
            for i, s in enumerate(oos_sorted[:top_k], 1):
                cat = s.get('category', '?')[:8]
                print(f"    {i:2d}. [{cat:8s}] {s['strategy_name'][:35]:35s}  PF={s['pf']:.3f}  WR={s['winrate']:.1f}%  trades={s['trade_count']}")
            all_oos_results.extend(oos_results)

        # === Phase 3: 頑健性テスト (上位戦略のみ) ===
        print(f"\n  Phase 3: 頑健性テスト...")
        robustness = _run_robustness_tests(
            top_classes, data_files, initial_balance, spread, commission, top_names,
        )
        all_robustness.extend(robustness)

        if robustness:
            for r in sorted(robustness, key=lambda x: x.get("spread_robustness", 0), reverse=True)[:5]:
                print(f"    {r['strategy_name'][:40]:40s}  spread頑健性={r['spread_robustness']:.2f}  PF@1x={r.get('pf_spread_1.0x', 0):.3f}  PF@2x={r.get('pf_spread_2.0x', 0):.3f}")

        # 上位戦略のCONFIGを次世代生成用に保存
        top_configs_for_next = []
        from engine.strategy_loader import extract_config_from_file
        for filename in os.listdir(generated_dir):
            if not filename.endswith(".py") or filename.startswith("_"):
                continue
            name = filename.replace(".py", "")
            if name in top_names:
                cfg = extract_config_from_file(os.path.join(generated_dir, filename))
                if cfg:
                    top_configs_for_next.append(cfg)

        # 承認判定 (OOS結果ベース)
        approval_source = oos_aggregated if oos_aggregated else is_aggregated
        approved_names = _approve_strategies(
            approval_source, generated_dir, approved_dir, approved_pf, approved_max_dd, min_trades
        )
        all_approved.extend(approved_names)

        if approved_names:
            print(f"\n  新規承認: {len(approved_names)} 戦略")
        else:
            print(f"\n  新規承認: なし")

        # 不採用をアーカイブ
        approved_set = set(approved_names) | top_names
        _archive_strategies(generated_dir, archived_dir, approved_set)

    # ================================================================
    # Walk-Forward テスト (承認済み戦略のみ)
    # ================================================================
    approved_classes = load_all_strategies(approved_dir)
    wf_results = []
    if approved_classes:
        print(f"\n{'='*70}")
        print(f"  Walk-Forward テスト ({len(approved_classes)} 承認済み戦略)")
        print(f"{'='*70}")
        wf_results = _run_walk_forward(
            approved_classes, data_files, initial_balance, spread, commission,
            n_windows=wf_windows, is_ratio=is_ratio,
        )
        if wf_results:
            wf_df = pd.DataFrame(wf_results)
            wf_csv = os.path.join(results_dir, "walk_forward_results.csv")
            wf_df.to_csv(wf_csv, index=False, encoding="utf-8-sig")
            print(f"\n  Walk-Forward結果:")
            for r in sorted(wf_results, key=lambda x: x.get("oos_pf_avg", 0), reverse=True):
                print(f"    {r['strategy_name'][:40]:40s}  IS_PF={r['is_pf_avg']:.3f}  OOS_PF={r['oos_pf_avg']:.3f}  OOS/IS={r['oos_is_ratio']:.2f}")

    # ================================================================
    # 最終レポート
    # ================================================================
    print(f"\n{'='*70}")
    print(f"  全ラウンド完了 - 最終レポート")
    print(f"{'='*70}")

    # OOS ランキング
    if all_oos_results:
        oos_ranking = create_ranking(
            all_oos_results, min_pf=filter_min_pf, max_dd_pct=filter_max_dd, min_trades=filter_min_trades,
        )
        save_oos_ranking(oos_ranking, results_dir)
        print(f"\n  OOSランキング保存: {os.path.join(results_dir, 'out_of_sample_ranking.csv')}")

    # 頑健性レポート
    if all_robustness:
        save_robustness_report(all_robustness, results_dir)
        print(f"  頑健性レポート保存: {os.path.join(results_dir, 'robustness_report.csv')}")

    # 詳細ブレイクダウン (通貨ペア別・時間帯別・時間足別)
    if all_oos_results:
        save_detail_breakdown(all_oos_results, results_dir)

    # 承認済み戦略の一覧
    approved_files = [
        f for f in os.listdir(approved_dir)
        if f.endswith(".py") and not f.startswith("_")
    ]
    print(f"\n  承認済み戦略 (strategies/approved/): {len(approved_files)} 個")
    for f in sorted(approved_files):
        print(f"    - {f}")

    logger.info("進化型研究ループ完了")
