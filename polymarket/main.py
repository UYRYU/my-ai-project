"""
Polymarket Tracker - エントリーポイント
引数によって動作を切り替える:
  (無し)                      : スケジューラ起動 (定期収集モード)
  --collect                   : 即時1回の取引収集 (日次/週次/全期間の合算)
  --analyze                   : 分析レポートを表示
  --leaderboard               : 全ウィンドウ(日次/週次/月次/全期間)×全種別のリーダーボード表示
  --leaderboard --window 1d   : 指定ウィンドウのみ表示 (1d/7d/30d/all)
  --leaderboard --type profit : 指定種別のみ表示 (profit/volume)
"""

import argparse
import sys

from loguru import logger

import config

# 起動時にログ設定 (stderrに色付き出力)
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level:<7}</level> | {message}",
    level="INFO",
)


def _cmd_collect() -> None:
    """即時1回の取引収集"""
    from tracker import collect_all
    collect_all()


def _cmd_analyze() -> None:
    """蓄積データの分析レポート"""
    from analyzer import print_report
    print_report()


def _cmd_leaderboard(window: str = None, board_type: str = None) -> None:
    """
    リーダーボードを取得して表示する。
    引数無しで呼ぶと全ウィンドウ × 全種別を表示。
    window / board_type を指定すると該当組み合わせのみ表示。
    """
    from leaderboard import get_leaderboard, print_leaderboard

    # 対象ウィンドウ/種別を決定
    windows = [window] if window else config.WINDOWS
    types = [board_type] if board_type else config.LEADERBOARD_TYPES

    any_data = False
    for bt in types:
        for w in windows:
            users = get_leaderboard(window=w, board_type=bt, save=True)
            label = config.WINDOW_LABELS.get(w, w)
            title = f"{label} ({w}) / {bt.upper()}"
            print_leaderboard(users, title=title)
            if users:
                any_data = True

    if not any_data:
        print("\n[!] リーダーボードを取得できませんでした (ネットワーク/APIを確認してください)")
    print()


def _cmd_schedule() -> None:
    """定期収集モード (デフォルト)"""
    from scheduler import run_scheduler
    run_scheduler()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Polymarket Tracker - 上位トレーダーの取引を追跡・分析"
    )
    parser.add_argument(
        "--collect",
        action="store_true",
        help="即時1回、全上位者の取引を収集する",
    )
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="蓄積データの分析レポートを表示する",
    )
    parser.add_argument(
        "--leaderboard",
        action="store_true",
        help="リーダーボードを表示する (--window/--type でフィルタ可)",
    )
    parser.add_argument(
        "--window",
        choices=config.WINDOWS,
        default=None,
        help="リーダーボードのウィンドウ (1d/7d/30d/all)。省略時は全て表示",
    )
    parser.add_argument(
        "--type",
        dest="board_type",
        choices=config.LEADERBOARD_TYPES,
        default=None,
        help="リーダーボードの種別 (profit/volume)。省略時は両方表示",
    )

    args = parser.parse_args()

    # 排他的に処理 (複数指定された場合は優先順に)
    if args.collect:
        _cmd_collect()
    elif args.analyze:
        _cmd_analyze()
    elif args.leaderboard:
        _cmd_leaderboard(window=args.window, board_type=args.board_type)
    else:
        # 引数無しならスケジューラ起動
        _cmd_schedule()


if __name__ == "__main__":
    main()
