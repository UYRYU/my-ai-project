"""Watchdog: main.py を自動再起動するラッパー。

機能:
  - main.py がクラッシュしたら自動再起動（指数バックオフ）
  - ネット切断を検知して復帰を待機
  - 最大再起動回数の制限
  - ログファイル出力（logs/ ディレクトリ）
  - Ctrl+C で正常終了（再起動しない）
  - タスクスケジューラからの起動に対応

Usage:
    python watchdog.py                     # 通常起動
    python watchdog.py --max-restarts 50   # 最大再起動回数
    pythonw watchdog.py                    # コンソール非表示（タスクスケジューラ用）
"""

import argparse
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# プロジェクトルートを確定（このファイルと同じディレクトリ）
PROJECT_DIR = Path(__file__).parent.resolve()
os.chdir(PROJECT_DIR)

# ログ設定
LOG_DIR = PROJECT_DIR / "logs"
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
    targets = [("8.8.8.8", 53), ("1.1.1.1", 53), ("208.67.222.222", 53)]
    for host, port in targets:
        try:
            sock = socket.create_connection((host, port), timeout=timeout)
            sock.close()
            return True
        except (socket.timeout, OSError):
            continue
    return False


def wait_for_network(check_interval: int = 10, max_wait: int = 7200) -> bool:
    """ネットワーク復帰を待機する（デフォルト最大2時間）。"""
    logger.warning("ネットワーク切断を検知。復帰を待機中...")
    waited = 0
    while waited < max_wait:
        if check_network():
            logger.info("ネットワーク復帰を確認。%d秒後に再開。", 5)
            time.sleep(5)  # 復帰直後は不安定な場合があるため少し待つ
            return True
        time.sleep(check_interval)
        waited += check_interval
        if waited % 60 == 0:
            logger.info("ネットワーク待機中... (%d分経過)", waited // 60)
    logger.error("ネットワーク復帰タイムアウト (%d秒)", max_wait)
    return False


def find_python() -> str:
    """venv の python を優先的に使用する。"""
    venv_python = PROJECT_DIR / "venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def run_tracker() -> int:
    """main.py を子プロセスとして実行する。終了コードを返す。"""
    python = find_python()
    script = str(PROJECT_DIR / "main.py")
    logger.info("トラッカー起動: %s %s", python, script)

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    try:
        proc = subprocess.Popen(
            [python, script],
            cwd=str(PROJECT_DIR),
            env=env,
        )
        proc.wait()
        return proc.returncode
    except KeyboardInterrupt:
        logger.info("Ctrl+C 受信。子プロセスを停止中...")
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        return -1
    except Exception as e:
        logger.error("プロセス起動エラー: %s", e)
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Watchdog: main.py 自動再起動")
    parser.add_argument("--max-restarts", type=int, default=9999,
                        help="最大再起動回数 (default: 9999)")
    parser.add_argument("--base-delay", type=int, default=5,
                        help="再起動の初期待機秒数 (default: 5)")
    parser.add_argument("--max-delay", type=int, default=300,
                        help="再起動の最大待機秒数 (default: 300)")
    args = parser.parse_args()

    restarts = 0
    delay = args.base_delay

    logger.info("========================================")
    logger.info("Watchdog 開始")
    logger.info("  プロジェクト: %s", PROJECT_DIR)
    logger.info("  Python: %s", find_python())
    logger.info("  最大再起動: %d回", args.max_restarts)
    logger.info("========================================")

    while restarts < args.max_restarts:
        # ネットワーク確認（MOCK モードでもネット確認はスキップしない）
        if not check_network():
            if not wait_for_network():
                logger.error("ネットワーク復帰できず。60秒後にリトライ...")
                time.sleep(60)
                continue  # 終了せずリトライ

        # トラッカー実行
        start_time = time.time()
        exit_code = run_tracker()
        elapsed = time.time() - start_time

        # Ctrl+C の場合は終了
        if exit_code == -1:
            logger.info("ユーザーにより停止。Watchdog 終了。")
            break

        # 正常終了 (exit_code == 0) → 再起動（main.pyが0で終了するのは想定外）
        if exit_code == 0 and elapsed > 60:
            logger.info("トラッカーが正常終了 (稼働%.0f秒)。再起動します。", elapsed)
        elif exit_code == 0:
            logger.info("トラッカーが即座に終了。設定を確認してください。")
            time.sleep(30)

        restarts += 1
        logger.warning(
            "トラッカー終了 (code=%d, 稼働%.0f秒)。再起動 %d/%d",
            exit_code, elapsed, restarts, args.max_restarts,
        )

        # 長時間稼働後のクラッシュはバックオフをリセット
        if elapsed > 600:
            delay = args.base_delay
            logger.info("長時間稼働後の停止。バックオフをリセット。")

        # ネットワーク起因の場合は復帰を待つ
        if not check_network():
            wait_for_network()
            delay = args.base_delay
        else:
            logger.info("%d秒後に再起動...", delay)
            try:
                time.sleep(delay)
            except KeyboardInterrupt:
                logger.info("待機中に Ctrl+C。終了。")
                break
            delay = min(delay * 2, args.max_delay)

    if restarts >= args.max_restarts:
        logger.error("最大再起動回数 (%d) に到達。終了します。", args.max_restarts)

    logger.info("=== Watchdog 終了 ===")


if __name__ == "__main__":
    main()
