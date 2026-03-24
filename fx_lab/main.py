"""FXスキャルピング戦略 研究工場 - メインエントリーポイント

使い方:
    python main.py
"""

import os
import sys
import logging
import yaml

from data_loader import discover_data_files
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


def main() -> None:
    # パスの基準をこのスクリプトのディレクトリにする
    base_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_dir)

    setup_logging("logs")
    logger = logging.getLogger(__name__)

    # 設定読み込み
    config_path = os.path.join("config", "settings.yaml")
    if not os.path.exists(config_path):
        logger.error(f"設定ファイルが見つかりません: {config_path}")
        sys.exit(1)

    settings = load_settings(config_path)
    logger.info("設定を読み込みました")

    initial_balance = settings.get("initial_balance", 100000)
    spread = settings.get("spread", 0.2)
    commission = settings.get("commission", 0.01)
    data_dir = settings.get("data_dir", "data/raw")
    results_dir = settings.get("results_dir", "results")
    strategies_dir = settings.get("strategies_dir", "strategies/generated")

    ranking_filters = settings.get("ranking_filters", {})
    min_pf = ranking_filters.get("min_pf", 1.2)
    max_dd_pct = ranking_filters.get("max_drawdown_pct", 15.0)
    min_trades = ranking_filters.get("min_trades", 100)

    # データファイル検出
    data_files = discover_data_files(data_dir)
    if not data_files:
        logger.error(f"データファイルが見つかりません: {data_dir}")
        logger.error("data/raw/ に USDJPY_M1.csv などのOHLCデータを配置してください")
        sys.exit(1)

    logger.info(f"データファイル数: {len(data_files)}")
    for d in data_files:
        logger.info(f"  {d['symbol']}_{d['timeframe']}: {d['filepath']}")

    # バックテスト実行
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

    # 全結果保存
    csv_dir = os.path.join(results_dir, "csv")
    save_all_results(all_results, csv_dir)

    # ランキング作成・保存
    ranking = create_ranking(all_results, min_pf=min_pf, max_dd_pct=max_dd_pct, min_trades=min_trades)
    ranked_dir = os.path.join(results_dir, "ranked")
    save_ranking(ranking, ranked_dir)

    # サマリー表示
    print_summary(ranking, all_results)

    logger.info("完了")


if __name__ == "__main__":
    main()
