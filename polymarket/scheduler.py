"""
Polymarket Tracker - スケジューラモジュール

3つのジョブを異なる頻度で実行:
  - シグナルスキャン  (5分ごと):  上位者の新規ベット検知 → ペーパー/ライブトレード
  - データ収集       (1時間ごと): リーダーボード更新 + 取引履歴収集 + 勝敗更新
  - 自動調整&レポート (6時間ごと): 戦略の自動チューニング + 日次レポート出力

2日間放置前提で、例外が発生してもスケジューラ自体は止まらないように作る。
各ジョブは try/except で保護、失敗しても次のサイクルで継続。
"""

import sys
import time
import traceback
from datetime import datetime

import schedule
from loguru import logger

import config
from tracker import collect_all
from resolver import update_results


# ジョブ間隔
SIGNAL_SCAN_INTERVAL_MINUTES = 5
AUTO_TUNE_INTERVAL_HOURS = 6


# ===== ログをファイルにも出力 (放置時の確認用) =====
logger.add(
    "data/scheduler.log",
    rotation="1 day",
    retention="7 days",
    level="INFO",
    encoding="utf-8",
)


def _job_collect() -> None:
    """1時間ごとのジョブ: データ収集 + 勝敗更新"""
    start = datetime.now()
    logger.info(f"[hourly] 開始: {start.strftime('%H:%M:%S')}")
    try:
        added = collect_all()
        logger.info(f"[hourly] 収集: 新規 {added} 件")

        stats = update_results()
        logger.info(
            f"[hourly] 勝敗更新: 決着 {stats['resolved']} / 未決 {stats['unresolved']}"
        )
    except Exception as e:
        logger.exception(f"[hourly] 例外: {e}")
    finally:
        elapsed = (datetime.now() - start).total_seconds()
        logger.info(f"[hourly] 完了 ({elapsed:.1f}秒)")


def _job_signal() -> None:
    """5分ごとのジョブ: シグナルスキャン → ベット実行"""
    start = datetime.now()
    logger.info(f"[signal] 開始: {start.strftime('%H:%M:%S')}")
    try:
        from leaderboard import get_tracked_traders
        from strategy import scan_for_signals, enrich_signals
        from executor import execute_signals, resolve_paper_trades, is_dry_run

        resolved = resolve_paper_trades()
        if resolved:
            logger.info(f"[signal] ペーパー {resolved} 件決済")

        # BL/WLを更新 (軽い処理なので毎回)
        from trader_stats import update_blacklist, update_whitelist
        blacklist = update_blacklist()
        whitelist = update_whitelist()
        logger.info(f"[signal] BL: {len(blacklist)} / WL: {len(whitelist)}")

        users = get_tracked_traders()
        if not users:
            logger.warning("[signal] 追跡対象なし")
            return

        signals = scan_for_signals(users)
        if not signals:
            logger.info("[signal] 新規シグナルなし")
            return

        enriched = enrich_signals(signals)
        if not enriched:
            return

        mode = "PAPER" if is_dry_run() else "LIVE"
        executed = execute_signals(enriched)
        logger.info(f"[signal] {mode}: {len(executed)} 件ベット")

    except Exception as e:
        logger.exception(f"[signal] 例外: {e}")
    finally:
        elapsed = (datetime.now() - start).total_seconds()
        logger.info(f"[signal] 完了 ({elapsed:.1f}秒)")


def _job_tune() -> None:
    """6時間ごとのジョブ: 自動チューニング + 日次レポート"""
    start = datetime.now()
    logger.info(f"[tune] 開始: {start.strftime('%H:%M:%S')}")
    try:
        from auto_tune import run_auto_tune
        summary = run_auto_tune()
        logger.info(f"[tune] 調整完了: {summary}")
    except Exception as e:
        logger.exception(f"[tune] auto_tune 例外: {e}")

    try:
        from daily_report import generate_report
        generate_report()
        logger.info(f"[tune] 日次レポート生成完了")
    except Exception as e:
        logger.exception(f"[tune] レポート例外: {e}")
    finally:
        elapsed = (datetime.now() - start).total_seconds()
        logger.info(f"[tune] 完了 ({elapsed:.1f}秒)")


def run_scheduler() -> None:
    """
    メインスケジューラ:
      - 5分ごと  : シグナルスキャン
      - 1時間ごと: データ収集
      - 6時間ごと: 自動調整 + 日次レポート
    """
    logger.info("=" * 60)
    logger.info("スケジューラ起動 (長期放置モード)")
    logger.info(f"  シグナルスキャン : 毎 {SIGNAL_SCAN_INTERVAL_MINUTES} 分")
    logger.info(f"  データ収集       : 毎 {config.SCHEDULE_INTERVAL_HOURS} 時間")
    logger.info(f"  自動調整+レポート : 毎 {AUTO_TUNE_INTERVAL_HOURS} 時間")
    logger.info("=" * 60)

    # 起動時に即実行
    _job_collect()
    _job_signal()
    _job_tune()

    # 定期登録
    schedule.every(SIGNAL_SCAN_INTERVAL_MINUTES).minutes.do(_job_signal)
    schedule.every(config.SCHEDULE_INTERVAL_HOURS).hours.do(_job_collect)
    schedule.every(AUTO_TUNE_INTERVAL_HOURS).hours.do(_job_tune)

    # 放置耐性: スケジュールループ自体が落ちないよう保護
    while True:
        try:
            schedule.run_pending()
            time.sleep(15)
        except KeyboardInterrupt:
            logger.info("スケジューラを停止 (Ctrl+C)")
            break
        except Exception as e:
            logger.exception(f"[scheduler] ループ内例外: {e}")
            traceback.print_exc()
            time.sleep(30)  # 例外時は少し待って継続


if __name__ == "__main__":
    run_scheduler()
