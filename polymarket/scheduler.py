"""
Polymarket Tracker - スケジューラモジュール

2つのジョブを異なる頻度で実行:
  - シグナルスキャン (5分ごと): 上位者の新規ベットを検知 → ペーパー/ライブトレード
  - データ収集 (1時間ごと): リーダーボード更新 + 取引履歴収集 + 勝敗更新
"""

import time
from datetime import datetime

import schedule
from loguru import logger

import config
from tracker import collect_all
from resolver import update_results


# シグナルスキャンの間隔 (分)
SIGNAL_SCAN_INTERVAL_MINUTES = 5


def _job_collect() -> None:
    """
    1時間ごとのジョブ: データ収集 + 勝敗更新
    """
    start = datetime.now()
    logger.info(f"[hourly] データ収集ジョブ開始: {start.strftime('%H:%M:%S')}")
    try:
        added = collect_all()
        logger.info(f"[hourly] 収集完了: 新規 {added} 件")

        stats = update_results()
        logger.info(
            f"[hourly] 勝敗更新: 決着 {stats['resolved']} 件 / "
            f"未決着 {stats['unresolved']} 件"
        )
    except Exception as e:
        logger.exception(f"[hourly] 例外発生: {e}")
    finally:
        elapsed = (datetime.now() - start).total_seconds()
        logger.info(f"[hourly] 完了 ({elapsed:.1f}秒)")


def _job_signal() -> None:
    """
    5分ごとのジョブ: シグナルスキャン → ベット実行
    """
    start = datetime.now()
    logger.info(f"[signal] スキャン開始: {start.strftime('%H:%M:%S')}")
    try:
        from leaderboard import get_tracked_traders
        from strategy import scan_for_signals, enrich_signals
        from executor import execute_signals, resolve_paper_trades, is_dry_run

        # オープンポジションの決済チェック
        resolved = resolve_paper_trades()
        if resolved:
            logger.info(f"[signal] ペーパートレード {resolved} 件決済")

        # ブラックリストを更新 (負けてるトレーダーを自動除外)
        from trader_stats import update_blacklist
        blacklist = update_blacklist()
        if blacklist:
            logger.info(f"[signal] ブラックリスト: {len(blacklist)} 人")

        # 追跡対象を取得 (キャッシュされたリーダーボードを使う)
        users = get_tracked_traders()
        if not users:
            logger.warning("[signal] 追跡対象なし")
            return

        # シグナルスキャン
        signals = scan_for_signals(users)
        if not signals:
            logger.info("[signal] 新規シグナルなし")
            return

        # トークンID/価格を付与
        enriched = enrich_signals(signals)
        if not enriched:
            return

        # ベット実行
        mode = "PAPER" if is_dry_run() else "LIVE"
        executed = execute_signals(enriched)
        logger.info(f"[signal] {mode}: {len(executed)} 件ベット実行")

    except Exception as e:
        logger.exception(f"[signal] 例外発生: {e}")
    finally:
        elapsed = (datetime.now() - start).total_seconds()
        logger.info(f"[signal] 完了 ({elapsed:.1f}秒)")


def run_scheduler() -> None:
    """
    メインスケジューラ:
      - 5分ごと: シグナルスキャン → トレード
      - 1時間ごと: データ収集 + 勝敗更新

    起動直後に両方を1回ずつ実行してから定期実行に入る。
    Ctrl+C で停止。
    """
    logger.info("=" * 50)
    logger.info("スケジューラ起動")
    logger.info(f"  シグナルスキャン : 毎 {SIGNAL_SCAN_INTERVAL_MINUTES} 分")
    logger.info(f"  データ収集       : 毎 {config.SCHEDULE_INTERVAL_HOURS} 時間")
    logger.info("=" * 50)

    # 起動時に即実行
    _job_collect()
    _job_signal()

    # 定期実行を登録
    schedule.every(SIGNAL_SCAN_INTERVAL_MINUTES).minutes.do(_job_signal)
    schedule.every(config.SCHEDULE_INTERVAL_HOURS).hours.do(_job_collect)

    try:
        while True:
            schedule.run_pending()
            time.sleep(15)  # 15秒ごとにチェック
    except KeyboardInterrupt:
        logger.info("スケジューラを停止しました (Ctrl+C)")


if __name__ == "__main__":
    run_scheduler()
