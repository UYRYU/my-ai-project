"""Monitor: 定期的にDBを確認し、アラートを発信する。

機能:
  1. 日次レポート自動保存 (report.py --v2-only --daily 相当)
  2. edge <= 0 になったら Discord 通知
  3. PF < 1.0 になったら Discord 通知
  4. 100トレード到達で通知
  5. Live移行可能になったら通知

Usage:
    python monitor.py                # 1回実行（タスクスケジューラ向け）
    python monitor.py --loop 600     # 10分間隔でループ実行
    python monitor.py --check-only   # アラートチェックのみ（レポート保存しない）
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MONITOR] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            LOG_DIR / f"monitor_{datetime.now().strftime('%Y%m%d')}.log",
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("monitor")

# アラート状態ファイル（同じアラートを何度も送らないため）
ALERT_STATE_FILE = Path(".monitor_state.json")


def load_alert_state() -> dict:
    if ALERT_STATE_FILE.exists():
        try:
            return json.loads(ALERT_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_alert_state(state: dict) -> None:
    ALERT_STATE_FILE.write_text(
        json.dumps(state, indent=2, default=str), encoding="utf-8"
    )


async def send_discord_alert(title: str, message: str, color: int = 0xFF0000) -> bool:
    """Discord Webhook でアラートを送信する。"""
    import httpx

    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")
    if not webhook_url:
        logger.info("[ALERT-LOCAL] %s: %s", title, message)
        return False

    embed = {
        "title": title,
        "description": message,
        "color": color,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json={"embeds": [embed]})
            resp.raise_for_status()
            logger.info("Discord通知送信: %s", title)
            return True
    except Exception as e:
        logger.error("Discord通知失敗: %s - %s", title, e)
        return False


async def load_trades(db_path: str) -> list[dict]:
    """DBから全paper_tradesを読み込む。"""
    import aiosqlite

    if not Path(db_path).exists():
        return []

    db = await aiosqlite.connect(db_path)
    cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='paper_trades'"
    )
    if not await cursor.fetchone():
        await db.close()
        return []

    db.row_factory = aiosqlite.Row
    cursor = await db.execute("SELECT * FROM paper_trades ORDER BY created_at ASC")
    rows = await cursor.fetchall()
    await db.close()
    return [dict(row) for row in rows]


async def run_checks(db_path: str, save_report: bool = True) -> None:
    """全チェックを実行する。"""
    from src.analytics import (
        check_v2_readiness,
        compute_edge_indicator,
        compute_summary,
        filter_by_model,
    )

    trades = await load_trades(db_path)
    v2_trades = filter_by_model(trades, "v2_binary")
    n = len(v2_trades)

    logger.info("v2_binary トレード数: %d", n)

    if n == 0:
        logger.info("v2トレードなし。スキップ。")
        return

    summary = compute_summary(v2_trades)
    edge = compute_edge_indicator(v2_trades)
    readiness = check_v2_readiness(trades)

    state = load_alert_state()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    alerts_sent = []

    # --- チェック 1: edge <= 0 ---
    if not edge["has_edge"] and n >= 10:
        alert_key = f"edge_negative_{today}"
        if alert_key not in state:
            await send_discord_alert(
                "Edge Alert: シグナルのエッジがマイナス",
                f"実績勝率: {edge['actual_win_rate']}%\n"
                f"期待勝率: {edge['expected_win_rate']}%\n"
                f"Edge: {edge['edge_pct']:+.1f}pp\n"
                f"トレード数: {n}",
                color=0xFF0000,
            )
            state[alert_key] = True
            alerts_sent.append("edge_negative")

    # --- チェック 2: PF < 1.0 ---
    pf = summary.get("profit_factor", 0)
    if pf < 1.0 and pf != 0 and n >= 10:
        alert_key = f"pf_low_{today}"
        if alert_key not in state:
            await send_discord_alert(
                "PF Alert: Profit Factor < 1.0",
                f"Profit Factor: {pf}\n"
                f"総損益: ${summary['total_pnl']:+.2f}\n"
                f"勝率: {summary['win_rate']}%\n"
                f"トレード数: {n}",
                color=0xFF8800,
            )
            state[alert_key] = True
            alerts_sent.append("pf_low")

    # --- チェック 3: 100トレード到達 ---
    if n >= 100:
        alert_key = "milestone_100"
        if alert_key not in state:
            await send_discord_alert(
                "Milestone: v2_binary 100トレード到達！",
                f"トレード数: {n}\n"
                f"勝率: {summary['win_rate']}%\n"
                f"総損益: ${summary['total_pnl']:+.2f}\n"
                f"Edge: {edge['edge_pct']:+.1f}pp\n"
                f"PF: {pf}",
                color=0x00FF00,
            )
            state[alert_key] = True
            alerts_sent.append("milestone_100")

    # --- チェック 4: Live移行可能 ---
    if readiness["all_passed"]:
        alert_key = "live_ready"
        if alert_key not in state:
            await send_discord_alert(
                "LIVE READY: 全条件クリア！",
                "v2_binary の検証が全条件を満たしました。\n"
                f"トレード数: {readiness['trade_count']}\n"
                f"Edge: {edge['edge_pct']:+.1f}pp\n"
                f"PF: {pf}\n\n"
                "案2 (edge パラメータ) への移行を検討してください。",
                color=0x00FF00,
            )
            state[alert_key] = True
            alerts_sent.append("live_ready")

    save_alert_state(state)

    if alerts_sent:
        logger.info("アラート送信: %s", ", ".join(alerts_sent))
    else:
        logger.info("アラートなし。(edge=%.1fpp, PF=%.2f, n=%d)", edge["edge_pct"], pf, n)

    # --- 日次レポート保存 ---
    if save_report:
        try:
            from report import export_csv, save_daily_report
            save_daily_report(v2_trades, None)
            export_csv(v2_trades, None, "paper_report_v2.csv")
            logger.info("日次レポート保存完了。")
        except Exception as e:
            logger.error("レポート保存エラー: %s", e)


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor: アラート & 日次レポート")
    parser.add_argument("--loop", type=int, default=0,
                        help="ループ間隔（秒）。0=1回実行して終了")
    parser.add_argument("--check-only", action="store_true",
                        help="アラートチェックのみ（レポート保存しない）")
    parser.add_argument("--db", default=os.getenv("DB_PATH", "tracker.db"),
                        help="DBパス")
    args = parser.parse_args()

    loop = asyncio.new_event_loop()

    if args.loop > 0:
        logger.info("=== Monitor ループ開始 (間隔: %d秒) ===", args.loop)
        try:
            while True:
                loop.run_until_complete(
                    run_checks(args.db, save_report=not args.check_only)
                )
                time.sleep(args.loop)
        except KeyboardInterrupt:
            logger.info("Monitor 停止。")
    else:
        logger.info("=== Monitor 1回実行 ===")
        loop.run_until_complete(
            run_checks(args.db, save_report=not args.check_only)
        )

    loop.close()


if __name__ == "__main__":
    main()
