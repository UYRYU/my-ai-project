"""
Polymarket Tracker - エントリーポイント
  (無し)                        : スケジューラ起動 (定期収集モード)
  --collect                     : 即時1回の取引収集
  --resolve                     : 勝敗結果を自動更新
  --analyze                     : 分析レポートを表示
  --leaderboard                 : リーダーボード表示
  --trade                       : シグナルスキャン → ベット実行 (ドライラン/ライブ)
  --paper                       : ペーパートレードのサマリーを表示
"""

import argparse
import sys

from loguru import logger

import config

# ログ設定
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level:<7}</level> | {message}",
    level="INFO",
)


def _cmd_collect() -> None:
    from tracker import collect_all
    collect_all()


def _cmd_resolve() -> None:
    from resolver import update_results
    stats = update_results()
    print(f"\n決着: {stats['resolved']} 件更新 / 未決着: {stats['unresolved']} 件 / エラー: {stats['errors']} 件\n")


def _cmd_analyze() -> None:
    from analyzer import print_report
    print_report()


def _cmd_leaderboard(window=None, board_type=None) -> None:
    from leaderboard import get_leaderboard, print_leaderboard
    windows = [window] if window else config.WINDOWS
    types = [board_type] if board_type else config.LEADERBOARD_TYPES
    any_data = False
    for bt in types:
        for w in windows:
            users = get_leaderboard(window=w, board_type=bt, save=True)
            label = config.WINDOW_LABELS.get(w, w)
            print_leaderboard(users, title=f"{label} ({w}) / {bt}")
            if users:
                any_data = True
    if not any_data:
        print("\n[!] リーダーボードを取得できませんでした")
    print()


def _cmd_trade() -> None:
    """シグナルスキャン → ベット実行 (ドライラン or ライブ)"""
    from leaderboard import get_tracked_traders
    from strategy import scan_for_signals, enrich_signals
    from executor import execute_signals, resolve_paper_trades, is_dry_run

    mode = "PAPER (ドライラン)" if is_dry_run() else "LIVE (実弾)"
    logger.info(f"トレードモード: {mode}")

    # 1. オープンポジションの決済チェック
    resolved = resolve_paper_trades()
    if resolved:
        logger.info(f"決済済み: {resolved} 件")

    # 2. 追跡対象トレーダーを取得
    users = get_tracked_traders()
    if not users:
        logger.error("追跡対象なし")
        return

    # 3. シグナルスキャン
    signals = scan_for_signals(users)
    if not signals:
        logger.info("新規シグナルなし")
        return

    # 4. シグナルにtoken_id/現在価格を付与
    enriched = enrich_signals(signals)
    if not enriched:
        logger.info("有効なシグナルなし (token_id取得失敗)")
        return

    # 5. ベット実行
    executed = execute_signals(enriched)
    logger.info(f"実行完了: {len(executed)} 件ベット")


def _cmd_paper() -> None:
    """ペーパートレードのサマリー表示"""
    from risk import print_paper_summary
    from executor import resolve_paper_trades

    # まず決済チェック
    resolve_paper_trades()
    # サマリー表示
    print_paper_summary()


def _cmd_stats() -> None:
    """トレーダー別成績を表示"""
    from trader_stats import print_trader_stats, update_blacklist
    update_blacklist()
    print_trader_stats()


def _cmd_schedule() -> None:
    from scheduler import run_scheduler
    run_scheduler()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Polymarket Tracker - 上位トレーダーの取引を追跡・分析・コピートレード"
    )
    parser.add_argument("--collect", action="store_true",
                        help="即時1回、全上位者の取引を収集する")
    parser.add_argument("--resolve", action="store_true",
                        help="勝敗結果を自動更新")
    parser.add_argument("--analyze", action="store_true",
                        help="蓄積データの分析レポートを表示する")
    parser.add_argument("--leaderboard", action="store_true",
                        help="リーダーボードを表示する")
    parser.add_argument("--trade", action="store_true",
                        help="シグナルスキャン → ベット実行 (ドライラン/ライブ)")
    parser.add_argument("--paper", action="store_true",
                        help="ペーパートレードのサマリーを表示")
    parser.add_argument("--stats", action="store_true",
                        help="トレーダー別成績を表示 (ブラックリスト更新も行う)")
    parser.add_argument("--window", choices=config.WINDOWS, default=None,
                        help="リーダーボードのウィンドウ")
    parser.add_argument("--type", dest="board_type",
                        choices=config.LEADERBOARD_TYPES, default=None,
                        help="リーダーボードの種別")

    args = parser.parse_args()

    if args.collect:
        _cmd_collect()
    elif args.resolve:
        _cmd_resolve()
    elif args.analyze:
        _cmd_analyze()
    elif args.leaderboard:
        _cmd_leaderboard(window=args.window, board_type=args.board_type)
    elif args.trade:
        _cmd_trade()
    elif args.paper:
        _cmd_paper()
    elif args.stats:
        _cmd_stats()
    else:
        _cmd_schedule()


if __name__ == "__main__":
    main()
