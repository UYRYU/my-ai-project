"""
Polymarket Tracker - Watchdog
main.py (スケジューラ) が落ちていたら自動で再起動する。

Windowsタスクスケジューラに5分おきで登録すると、
放置中にクラッシュしても5分以内に復活する。

使い方 (Windows Task Scheduler):
  - タスク名: PolyTracker-Watchdog
  - 実行コマンド: python C:\\bot\\my-ai-project\\polymarket\\watchdog.py
  - トリガー: 5分おき / PCログオン時
  - 作業フォルダ: C:\\bot\\my-ai-project\\polymarket
"""

import os
import subprocess
import sys
import time
from datetime import datetime

# ログ保存先
LOG_PATH = "data/watchdog.log"

# main.py を起動するコマンド
PYTHON_EXE = sys.executable  # 今使ってるPython
MAIN_SCRIPT = "main.py"

# プロセス識別用のマーカー (タスクマネージャーで見分ける用)
MARKER = "polymarket_scheduler_main"


def _log(msg: str) -> None:
    """シンプルなログ書き込み"""
    line = f"{datetime.now().isoformat()} {msg}"
    print(line)
    try:
        os.makedirs(os.path.dirname(LOG_PATH) or ".", exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _is_running() -> bool:
    """
    main.py が既に動いてるかチェックする (Windows限定)。
    tasklist で python プロセスを探して、コマンドラインに main.py が入ってるか見る。
    """
    try:
        # Windows: tasklist /V /FI "IMAGENAME eq python.exe" /FO CSV
        if os.name == "nt":
            output = subprocess.check_output(
                ['wmic', 'process', 'where', 'name="python.exe"', 'get', 'commandline', '/format:list'],
                stderr=subprocess.DEVNULL,
                timeout=10,
            ).decode("utf-8", errors="ignore")
            # main.py & (polymarket フォルダのもの)  が存在するか
            for line in output.split("\n"):
                if "main.py" in line and "polymarket" in line.lower():
                    # watchdog自身でないことを確認
                    if "watchdog.py" not in line:
                        return True
            return False
        else:
            # Linux/Mac用
            output = subprocess.check_output(
                ["pgrep", "-f", "main.py"],
                stderr=subprocess.DEVNULL,
            )
            return bool(output.strip())
    except Exception:
        return False


def _start_main() -> None:
    """main.py を起動する (バックグラウンド)"""
    try:
        if os.name == "nt":
            # Windows: 新しいコンソールで起動
            subprocess.Popen(
                [PYTHON_EXE, MAIN_SCRIPT],
                creationflags=subprocess.CREATE_NEW_CONSOLE,
                cwd=os.path.dirname(os.path.abspath(__file__)),
            )
        else:
            subprocess.Popen(
                [PYTHON_EXE, MAIN_SCRIPT],
                cwd=os.path.dirname(os.path.abspath(__file__)),
            )
        _log("[watchdog] main.py を起動しました")
    except Exception as e:
        _log(f"[watchdog] 起動失敗: {e}")


def check_and_restart() -> None:
    """main.py が死んでたら再起動する"""
    if _is_running():
        _log("[watchdog] main.py は稼働中")
    else:
        _log("[watchdog] main.py が停止している → 再起動")
        _start_main()


if __name__ == "__main__":
    check_and_restart()
