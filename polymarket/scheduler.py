"""
Polymarket Tracker - スケジューラモジュール
指定間隔 (デフォルト 1時間) ごとに collect_all() を実行する
"""

import time
from datetime import datetime

import schedule
from loguru import logger

import config
from tracker import collect_all


def _job() -> None:
    """
    定期実行されるジョブ本体。
    開始時刻・取得件数・完了時刻をログ出力する。
    """
    start = datetime.now()
    logger.info(f"[scheduler] ジョブ開始: {start.isoformat()}")
    try:
        added = collect_all()
        logger.info(f"[scheduler] ジョブ完了: 新規 {added} 件")
    except Exception as e:
        logger.exception(f"[scheduler] ジョブ内で例外発生: {e}")
    finally:
        end = datetime.now()
        elapsed = (end - start).total_seconds()
        logger.info(f"[scheduler] 経過時間: {elapsed:.1f} 秒")


def run_scheduler() -> None:
    """
    定期収集モードのエントリーポイント。
    起動直後に1回実行してから、以降は設定された間隔で繰り返す。
    Ctrl+Cで停止可能。
    """
    interval = config.SCHEDULE_INTERVAL_HOURS
    logger.info(f"スケジューラを開始します (毎 {interval} 時間)")

    # 起動時に即1回実行
    _job()

    # 以降は間隔ごとに実行
    schedule.every(interval).hours.do(_job)

    try:
        while True:
            schedule.run_pending()
            time.sleep(30)  # 30秒ごとにスケジュールチェック
    except KeyboardInterrupt:
        logger.info("スケジューラを停止しました (Ctrl+C)")


if __name__ == "__main__":
    run_scheduler()
