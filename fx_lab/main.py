"""FXスキャルピング戦略 自動研究工場 v2 - メインエントリーポイント

使い方:
    python main.py                      # 進化型研究ループ（デフォルト）
    python main.py --single             # 単発バックテスト
    python main.py --rounds 10          # ラウンド数指定
    python main.py --strategies 100     # ラウンドあたり戦略数指定
    python main.py --import-mt          # MT4/MT5 CSVインポートのみ
"""

import os
import sys
import argparse
import logging
import yaml

from data_loader import discover_data_files, batch_convert_mt_csv
from runner import run_all_backtests
from report import create_ranking, save_ranking, save_all_results, print_summary


def setup_logging(log_dir: str) -> None:
    os.makedirs(log_dir, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(os.path.join(log_dir, "fx_lab.log"), encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def load_settings(config_path: str) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def import_mt_data(settings: dict) -> None:
    """MT4/MT5 CSVインポート"""
    logger = logging.getLogger(__name__)
    mt_dir = settings.get("mt_import_dir", "data/mt_import")
    data_dir = settings.get("data_dir", "data/raw")

    if not os.path.isdir(mt_dir):
        logger.info(f"MT4/MT5インポートディレクトリが存在しません: {mt_dir}")
        logger.info("ディレクトリを作成しました。MT4/MT5のCSVを配置してください。")
        os.makedirs(mt_dir, exist_ok=True)
        return

    csv_files = [f for f in os.listdir(mt_dir) if f.endswith(".csv")]
    if not csv_files:
        logger.info(f"インポート対象CSVなし: {mt_dir}")
        return

    logger.info(f"MT4/MT5 CSV {len(csv_files)} 件をインポート中...")
    converted = batch_convert_mt_csv(mt_dir, data_dir)
    logger.info(f"インポート完了: {len(converted)} 件")


def run_single_mode(settings: dict) -> None:
    """単発バックテストモード"""
    logger = logging.getLogger(__name__)

    initial_balance = settings.get("initial_balance", 100000)
    spread = settings.get("spread", 0.02)
    commission = settings.get("commission", 0.005)
    data_dir = settings.get("data_dir", "data/raw")
    results_dir = settings.get("results_dir", "results")
    strategies_dir = settings.get("strategies_dir", "strategies/generated")

    ranking_filters = settings.get("ranking_filters", {})
    min_pf = ranking_filters.get("min_pf", 1.2)
    max_dd_pct = ranking_filters.get("max_drawdown_pct", 15.0)
    min_trades = ranking_filters.get("min_trades", 100)

    data_files = discover_data_files(data_dir)
    if not data_files:
        logger.error(f"データファイルが見つかりません: {data_dir}")
        sys.exit(1)

    logger.info(f"データファイル数: {len(data_files)}")
    logger.info("バックテスト開始...")

    all_results = run_all_backtests(
        data_files=data_files,
        strategies_dir=strategies_dir,
        initial_balance=initial_balance,
        spread=spread,
        commission=commission,
    )

    if not all_results:
        logger.warning("バックテスト結果がありません")
        sys.exit(1)

    csv_dir = os.path.join(results_dir, "csv")
    save_all_results(all_results, csv_dir)

    ranking = create_ranking(all_results, min_pf=min_pf, max_dd_pct=max_dd_pct, min_trades=min_trades)
    ranked_dir = os.path.join(results_dir, "ranked")
    save_ranking(ranking, ranked_dir)

    print_summary(ranking, all_results)
    logger.info("完了")


def run_evolution_mode(settings: dict) -> None:
    """進化型研究ループモード"""
    from engine.evolution import run_evolution
    run_evolution(settings)


def main() -> None:
    parser = argparse.ArgumentParser(description="FXスキャルピング戦略 自動研究工場 v2")
    parser.add_argument("--single", action="store_true", help="単発バックテストモード")
    parser.add_argument("--rounds", type=int, default=None, help="研究ラウンド数を上書き")
    parser.add_argument("--strategies", type=int, default=None, help="ラウンドあたり戦略数を上書き")
    parser.add_argument("--import-mt", action="store_true", help="MT4/MT5 CSVインポートのみ実行")
    parser.add_argument("--explore", action="store_true", help="RSI逆張り深掘り探索モード")
    parser.add_argument("--explore-struct", action="store_true", help="RSI+構造フィルタ深掘り探索モード")
    parser.add_argument("--scalp", action="store_true", help="M1スキャルピング探索モード")
    parser.add_argument("--scalp-ecn", action="store_true", help="ECN口座前提M1スキャル探索")
    args = parser.parse_args()

    # パスの基準をこのスクリプトのディレクトリにする
    base_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_dir)

    setup_logging("logs")
    logger = logging.getLogger(__name__)

    config_path = os.path.join("config", "settings.yaml")
    if not os.path.exists(config_path):
        logger.error(f"設定ファイルが見つかりません: {config_path}")
        sys.exit(1)

    settings = load_settings(config_path)
    logger.info("設定を読み込みました")

    # MT4/MT5データがあればインポート
    import_mt_data(settings)

    if args.import_mt:
        logger.info("MT4/MT5インポートのみ完了")
        return

    # コマンドライン引数で上書き
    if args.rounds is not None:
        settings.setdefault("research", {})["rounds"] = args.rounds
    if args.strategies is not None:
        settings.setdefault("research", {})["strategies_per_round"] = args.strategies

    if args.scalp_ecn:
        logger.info("モード: ECN口座前提M1スキャル探索")
        from explore_m1_ecn import run_ecn_scalp
        run_ecn_scalp(settings)
    elif args.scalp:
        logger.info("モード: M1スキャルピング探索")
        from explore_m1_scalp import run_m1_scalp_exploration
        run_m1_scalp_exploration(settings)
    elif args.explore_struct:
        logger.info("モード: RSI+構造フィルタ深掘り探索")
        from explore_rsi_structure import run_structure_exploration
        run_structure_exploration(settings)
    elif args.explore:
        logger.info("モード: RSI逆張り深掘り探索")
        from explore_rsi import run_exploration
        run_exploration(settings)
    elif args.single:
        logger.info("モード: 単発バックテスト")
        run_single_mode(settings)
    else:
        logger.info("モード: 進化型研究ループ v2")
        run_evolution_mode(settings)


if __name__ == "__main__":
    main()
