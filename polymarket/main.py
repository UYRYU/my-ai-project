"""
Polymarket Tracker - エントリーポイント
引数によって動作を切り替える:
  (無し)         : スケジューラ起動 (定期収集モード)
  --collect      : 即時1回の取引収集
  --analyze      : 分析レポートを表示
  --leaderboard  : 最新リーダーボードを表示
"""

import argparse
import sys

from loguru import logger

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


def _cmd_leaderboard() -> None:
    """最新リーダーボードを取得して表示"""
    from leaderboard import get_leaderboard
    users = get_leaderboard()
    if not users:
        print("リーダーボードを取得できませんでした")
        return
    print("\n===== Polymarket リーダーボード (Top) =====")
    print(f"{'順位':<6}{'ユーザー名':<22}{'利益(USD)':>16}  アドレス")
    print("-" * 80)
    for i, u in enumerate(users, 1):
        name = u.get("username", "")[:20] or "(no name)"
        profit = u.get("profit", 0.0)
        addr = u.get("address", "")
        print(f"{i:<6}{name:<22}{profit:>16,.2f}  {addr}")
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
        help="最新のリーダーボードを表示する",
    )

    args = parser.parse_args()

    # 排他的に処理 (複数指定された場合は優先順に)
    if args.collect:
        _cmd_collect()
    elif args.analyze:
        _cmd_analyze()
    elif args.leaderboard:
        _cmd_leaderboard()
    else:
        # 引数無しならスケジューラ起動
        _cmd_schedule()


if __name__ == "__main__":
    main()
