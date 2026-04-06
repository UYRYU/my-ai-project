"""Watchdog: main.py を自動再起動するラッパー。

機能:
  - main.py がクラッシュしたら自動再起動（指数バックオフ）
  - ネット切断を検知して復帰を待機
  - 最大再起動回数の制限
  - ログファイル出力

Usage:
    python watchdog.py              # 通常起動
    python watchdog.py --max-restarts 50  # 最大再起動回数を指定
"""

import argparse
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ログ設定
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WATCHDOG] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            LOG_DIR / f"watchdog_{datetime.now().strftime('%Y%m%d')}.log",
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("watchdog")


def check_network(timeout: int = 5) -> bool:
    """ネットワーク接続を確認する。"""
    import socket
    targets = [("8.8.8.8", 53), ("1.1.1.1", 53)]
    for host, port in targets:
        try:
            sock = socket.create_connection((host, port), timeout=timeout)
            sock.close()
            return True
        except (socket.timeout, OSError):
            continue
    return False


def wait_for_network(check_interval: int = 10, max_wait: int = 3600) -> bool:
    """ネットワーク復帰を待機する。"""
    logger.warning("ネットワーク切断を検知。復帰を待機中...")
    waited = 0
    while waited < max_wait:
        if check_network():
            logger.info("ネットワーク復帰を確認。")
            return True
        time.sleep(check_interval)
        waited += check_interval
        if waited % 60 == 0:
            logger.info("ネットワーク待機中... (%d秒経過)", waited)
    logger.error("ネットワーク復帰タイムアウト (%d秒)", max_wait)
    return False


def run_tracker() -> int:
    """main.py を子プロセスとして実行する。終了コードを返す。"""
    python = sys.executable
    script = str(Path(__file__).parent / "main.py")
    logger.info("トラッカー起動: %s %s", python, script)

    try:
        result = subprocess.run(
            [python, script],
            cwd=str(Path(__file__).parent),
            timeout=None,
        )
        return result.returncode
    except KeyboardInterrupt:
        logger.info("Ctrl+C 受信。停止します。")
        return -1
    except Exception as e:
        logger.error("プロセス起動エラー: %s", e)
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Watchdog: main.py 自動再起動")
    parser.add_argument("--max-restarts", type=int, default=100,
                        help="最大再起動回数 (default: 100)")
    parser.add_argument("--base-delay", type=int, default=5,
                        help="再起動の初期待機秒数 (default: 5)")
    parser.add_argument("--max-delay", type=int, default=300,
                        help="再起動の最大待機秒数 (default: 300)")
    args = parser.parse_args()

    restarts = 0
    delay = args.base_delay

    logger.info("=== Watchdog 開始 (最大再起動: %d回) ===", args.max_restarts)

    while restarts < args.max_restarts:
        # ネットワーク確認
        if not check_network():
            if not wait_for_network():
                logger.error("ネットワーク復帰できず。終了します。")
                break

        # トラッカー実行
        start_time = time.time()
        exit_code = run_tracker()
        elapsed = time.time() - start_time

        # Ctrl+C の場合は終了
        if exit_code == -1:
            logger.info("ユーザーにより停止。")
            break

        # 正常終了 (exit_code == 0) も終了
        if exit_code == 0:
            logger.info("トラッカーが正常終了しました。")
            break

        restarts += 1
        logger.warning(
            "トラッカーが異常終了 (code=%d, 稼働時間=%.0f秒)。再起動 %d/%d",
            exit_code, elapsed, restarts, args.max_restarts,
        )

        # 長時間稼働後のクラッシュはバックオフをリセット
        if elapsed > 600:
            delay = args.base_delay
            logger.info("長時間稼働後のクラッシュ。バックオフをリセット。")

        # ネットワーク起因の場合は復帰を待つ
        if not check_network():
            wait_for_network()
            delay = args.base_delay
        else:
            logger.info("%d秒後に再起動...", delay)
            time.sleep(delay)
            delay = min(delay * 2, args.max_delay)

    if restarts >= args.max_restarts:
        logger.error("最大再起動回数 (%d) に到達。終了します。", args.max_restarts)

    logger.info("=== Watchdog 終了 ===")


if __name__ == "__main__":
    main()
