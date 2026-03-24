"""進化ループエンジン

複数ラウンドにわたり戦略を生成→テスト→選別→再生成するサイクルを回す。
"""

import os
import shutil
import logging
import json
from datetime import datetime

import pandas as pd

from engine.strategy_generator import generate_and_write, write_strategy_file
from engine.strategy_mutator import generate_next_generation, analyze_top_features
from engine.strategy_loader import load_all_strategies, extract_all_configs
from data_loader import load_ohlc, discover_data_files
from metrics import evaluate_strategy
from report import create_ranking, save_ranking, save_all_results, print_summary

from tqdm import tqdm

logger = logging.getLogger(__name__)


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


def _run_backtest_batch(
    strategy_classes: list,
    data_files: list[dict],
    initial_balance: float,
    spread: float,
    commission: float,
) -> list[dict]:
    """全データ x 全戦略のバックテスト実行"""
    results = []
    total = len(data_files) * len(strategy_classes)

    with tqdm(total=total, desc="  バックテスト", leave=False) as pbar:
        for data_info in data_files:
            symbol = data_info["symbol"]
            timeframe = data_info["timeframe"]

            try:
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
        max_dd_pct=("max_dd_pct", "max"),  # 最悪のDDを採用
        total_pnl=("total_pnl", "sum"),
        avg_holding_seconds=("avg_holding_seconds", "mean"),
        trade_count=("trade_count", "sum"),
    ).reset_index()

    return agg.to_dict("records")


def _select_top_k(results: list[dict], top_k: int, min_pf: float, min_trades: int) -> list[dict]:
    """上位K戦略を選出

    フィルタ条件を満たす戦略が十分にない場合は、
    取引回数>0の戦略をPF降順で選出する（進化ループを止めないため）。
    """
    qualified = [
        r for r in results
        if r.get("pf", 0) >= min_pf and r.get("trade_count", 0) >= min_trades
    ]
    qualified.sort(key=lambda x: x.get("pf", 0), reverse=True)

    if len(qualified) >= top_k:
        return qualified[:top_k]

    # フォールバック: 取引実績のある全戦略からPF上位を選出
    fallback = [r for r in results if r.get("trade_count", 0) > 0]
    fallback.sort(key=lambda x: x.get("pf", 0), reverse=True)
    return fallback[:top_k]


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


def run_evolution(settings: dict) -> None:
    """進化型研究ループのメイン実行"""
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

    all_approved = []
    global_best_results = []
    top_configs_for_next = []

    for gen in range(1, rounds + 1):
        print(f"\n{'='*70}")
        print(f"  ラウンド {gen}/{rounds}")
        print(f"{'='*70}")
        logger.info(f"=== ラウンド {gen}/{rounds} 開始 ===")

        # 戦略生成
        _clear_directory(generated_dir)

        if gen == 1 or not top_configs_for_next:
            # 初回: 完全ランダム生成
            logger.info(f"初回ランダム生成: {strats_per_round} 個")
            generate_and_write(strats_per_round, generated_dir, base_seed=gen * 1000)
        else:
            # 2回目以降: 上位戦略ベースの次世代生成
            logger.info(f"進化生成 (親: {len(top_configs_for_next)} 戦略)")
            features = analyze_top_features(top_configs_for_next)
            logger.info(f"  上位シグナル分布: {features['signal_types']}")
            next_gen_configs = generate_next_generation(
                top_configs_for_next,
                count=strats_per_round,
                base_seed=gen * 1000,
            )
            for cfg in next_gen_configs:
                write_strategy_file(cfg, generated_dir)

        # 戦略読み込み
        strategy_classes = load_all_strategies(generated_dir)
        if not strategy_classes:
            logger.warning("戦略の読み込みに失敗")
            continue

        logger.info(f"読み込んだ戦略数: {len(strategy_classes)}")

        # バックテスト実行
        results = _run_backtest_batch(
            strategy_classes, data_files, initial_balance, spread, commission
        )

        if not results:
            logger.warning("バックテスト結果なし")
            continue

        # ラウンド結果保存
        gen_filename = f"generation_{gen:03d}.csv"
        gen_filepath = os.path.join(generations_dir, gen_filename)
        pd.DataFrame(results).to_csv(gen_filepath, index=False, encoding="utf-8-sig")
        logger.info(f"ラウンド結果保存: {gen_filepath}")

        # 戦略ごとの集約結果
        aggregated = _aggregate_by_strategy(results)

        # 上位K戦略を抽出
        top_strategies = _select_top_k(aggregated, top_k, filter_min_pf, filter_min_trades)
        top_names = {s["strategy_name"] for s in top_strategies}

        print(f"\n  上位 {len(top_strategies)} 戦略:")
        for i, s in enumerate(top_strategies, 1):
            print(f"    {i:2d}. {s['strategy_name'][:40]:40s}  PF={s['pf']:.3f}  WR={s['winrate']:.1f}%  DD={s['max_dd_pct']:.1f}%  trades={s['trade_count']}")

        # 上位戦略のCONFIGを次世代生成用に保存
        top_configs_for_next = []
        for filename in os.listdir(generated_dir):
            if not filename.endswith(".py") or filename.startswith("_"):
                continue
            name = filename.replace(".py", "")
            if name in top_names:
                from engine.strategy_loader import extract_config_from_file
                cfg = extract_config_from_file(os.path.join(generated_dir, filename))
                if cfg:
                    top_configs_for_next.append(cfg)

        # 承認判定
        approved_names = _approve_strategies(
            aggregated, generated_dir, approved_dir, approved_pf, approved_max_dd, min_trades
        )
        all_approved.extend(approved_names)

        if approved_names:
            print(f"\n  新規承認: {len(approved_names)} 戦略")
        else:
            print(f"\n  新規承認: なし")

        # 不採用をアーカイブ
        approved_set = set(approved_names) | top_names
        _archive_strategies(generated_dir, archived_dir, approved_set)

        # ベスト結果に追加
        global_best_results.extend(results)

    # ================================================================
    # 最終レポート
    # ================================================================
    print(f"\n{'='*70}")
    print(f"  全ラウンド完了 - 最終レポート")
    print(f"{'='*70}")

    # 全ラウンドの結果からランキング
    if global_best_results:
        # 全結果保存
        all_csv = os.path.join(results_dir, "csv", "all_results.csv")
        os.makedirs(os.path.dirname(all_csv), exist_ok=True)
        pd.DataFrame(global_best_results).to_csv(all_csv, index=False, encoding="utf-8-sig")

        # ランキング
        ranking = create_ranking(
            global_best_results,
            min_pf=filter_min_pf,
            max_dd_pct=filter_max_dd,
            min_trades=filter_min_trades,
        )
        save_ranking(ranking, ranked_dir)

        # ベスト保存
        best_csv = os.path.join(best_dir, "best_strategies.csv")
        ranking.head(20).to_csv(best_csv, encoding="utf-8-sig")

        print_summary(ranking, global_best_results)

    # 承認済み戦略の一覧
    approved_files = [
        f for f in os.listdir(approved_dir)
        if f.endswith(".py") and not f.startswith("_")
    ]
    print(f"\n  承認済み戦略 (strategies/approved/): {len(approved_files)} 個")
    for f in sorted(approved_files):
        print(f"    - {f}")

    logger.info("進化型研究ループ完了")
