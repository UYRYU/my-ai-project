"""Paper取引のパフォーマンスレポートを生成する。

Usage:
    python report.py              # Richターミナル表示
    python report.py --csv        # CSVにもエクスポート
    python report.py --json       # JSON出力
"""

import argparse
import asyncio
import csv
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

load_dotenv()

# Windows asyncio 互換性
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def load_data(db_path: str) -> tuple[list[dict], dict]:
    """DBからPaper取引データと集計を読み込む。"""
    import aiosqlite

    db = await aiosqlite.connect(db_path)

    # paper_tradesテーブルの存在確認
    cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='paper_trades'"
    )
    if not await cursor.fetchone():
        await db.close()
        return [], {
            "total_trades": 0, "wins": 0, "losses": 0,
            "win_rate": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
            "total_pnl": 0.0, "max_consecutive_losses": 0,
            "avg_holding_minutes": 0.0, "best_trade": 0.0, "worst_trade": 0.0,
        }

    # 全取引取得
    db.row_factory = aiosqlite.Row
    cursor = await db.execute(
        "SELECT * FROM paper_trades ORDER BY created_at ASC"
    )
    rows = await cursor.fetchall()
    trades = [dict(row) for row in rows]

    # 集計
    total = len(trades)
    if total == 0:
        await db.close()
        return trades, {
            "total_trades": 0, "wins": 0, "losses": 0,
            "win_rate": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
            "total_pnl": 0.0, "max_consecutive_losses": 0,
            "avg_holding_minutes": 0.0, "best_trade": 0.0, "worst_trade": 0.0,
        }

    wins = [t for t in trades if t["result"] == "win"]
    losses = [t for t in trades if t["result"] == "loss"]

    pnls = [t["pnl_usd"] for t in trades]
    win_pnls = [t["pnl_usd"] for t in wins]
    loss_pnls = [t["pnl_usd"] for t in losses]

    # 最大連敗
    max_streak = 0
    current_streak = 0
    for t in trades:
        if t["result"] == "loss":
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 0

    summary = {
        "total_trades": total,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / total * 100, 1),
        "avg_win": round(sum(win_pnls) / len(win_pnls), 2) if win_pnls else 0.0,
        "avg_loss": round(sum(loss_pnls) / len(loss_pnls), 2) if loss_pnls else 0.0,
        "total_pnl": round(sum(pnls), 2),
        "max_consecutive_losses": max_streak,
        "avg_holding_minutes": round(
            sum(t["holding_minutes"] for t in trades) / total, 1
        ),
        "best_trade": round(max(pnls), 2),
        "worst_trade": round(min(pnls), 2),
    }

    await db.close()
    return trades, summary


def show_report(trades: list[dict], summary: dict, console: Console) -> None:
    """Richでレポートを表示する。"""
    console.print()

    # --- ヘッダー ---
    banner = Text()
    banner.append("  Paper Trading Performance Report  ", style="bold white on magenta")
    console.print(Panel(banner, style="magenta", expand=False))
    console.print()

    if summary["total_trades"] == 0:
        console.print("  [yellow]Paper取引データがありません。[/yellow]")
        console.print("  python main.py でトラッカーを起動してデータを蓄積してください。")
        return

    # --- サマリーパネル ---
    pnl_style = "green" if summary["total_pnl"] >= 0 else "red"
    wr_style = "green" if summary["win_rate"] >= 50 else "red"

    summary_text = (
        f"[bold]総トレード数:[/bold]    {summary['total_trades']}\n"
        f"[bold]勝敗:[/bold]            "
        f"[green]{summary['wins']}W[/green] / "
        f"[red]{summary['losses']}L[/red]\n"
        f"[bold]勝率:[/bold]            [{wr_style}]{summary['win_rate']}%[/{wr_style}]\n"
        f"[bold]平均利益:[/bold]        [green]${summary['avg_win']:+.2f}[/green]\n"
        f"[bold]平均損失:[/bold]        [red]${summary['avg_loss']:+.2f}[/red]\n"
        f"[bold]総損益:[/bold]          [{pnl_style}]${summary['total_pnl']:+.2f}[/{pnl_style}]\n"
        f"[bold]ベスト:[/bold]          [green]${summary['best_trade']:+.2f}[/green]\n"
        f"[bold]ワースト:[/bold]        [red]${summary['worst_trade']:+.2f}[/red]\n"
        f"[bold]最大連敗:[/bold]        {summary['max_consecutive_losses']}\n"
        f"[bold]平均保有時間:[/bold]    {summary['avg_holding_minutes']}分"
    )
    console.print(Panel(summary_text, title="Performance Summary", style="cyan", expand=False))
    console.print()

    # --- 取引一覧テーブル ---
    table = Table(title="Paper Trades (全件)", show_lines=False, padding=(0, 1))
    table.add_column("#", style="dim", width=4)
    table.add_column("Signal Time", style="dim", width=20)
    table.add_column("Market", style="white", max_width=30)
    table.add_column("Direction", width=10)
    table.add_column("Entry", justify="right", width=8)
    table.add_column("Exit", justify="right", width=8)
    table.add_column("Amount", style="yellow", justify="right", width=10)
    table.add_column("PnL", justify="right", width=10)
    table.add_column("Hold", justify="right", width=8)
    table.add_column("Result", width=6)

    for i, t in enumerate(trades, 1):
        pnl = t["pnl_usd"]
        pnl_s = "green" if pnl >= 0 else "red"
        dir_s = "green" if "Buy" in (t.get("direction") or "") else "red"
        result_s = "green" if t["result"] == "win" else "red"

        signal_time = t.get("signal_time", "")
        if "T" in signal_time:
            signal_time = signal_time.replace("T", " ")[:19]

        table.add_row(
            str(i),
            signal_time,
            (t.get("market_title") or "")[:30],
            Text(t.get("direction", ""), style=dir_s),
            f"{t['entry_price']:.2%}",
            f"{t['exit_price']:.2%}",
            f"${t['entry_amount_usd']:.0f}",
            Text(f"${pnl:+.2f}", style=pnl_s),
            f"{t['holding_minutes']:.0f}m",
            Text(t["result"].upper(), style=result_s),
        )

    console.print(table)
    console.print()

    # --- 判断基準 ---
    console.print(
        Panel(
            "[bold]Paper検証の合格基準（推奨）:[/bold]\n\n"
            "  1. 最低50トレード以上を蓄積\n"
            "  2. 勝率 50% 以上\n"
            "  3. 総損益がプラス\n"
            "  4. 最大連敗 5回以下\n"
            "  5. avg_win / |avg_loss| > 1.0 (リスクリワード比)\n"
            "  6. 異なる時間帯・マーケットで安定\n\n"
            "[dim]全基準を満たすまでは live に移行しないでください。[/dim]",
            title="Live移行判断基準",
            style="yellow",
            expand=False,
        )
    )


def export_csv(trades: list[dict], summary: dict, path: str = "paper_report.csv") -> None:
    """レポートをCSVに出力する。"""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        # サマリーセクション
        writer.writerow(["=== Performance Summary ==="])
        for key, val in summary.items():
            writer.writerow([key, val])
        writer.writerow([])

        # 取引詳細
        writer.writerow(["=== Trade Details ==="])
        if trades:
            writer.writerow(trades[0].keys())
            for t in trades:
                writer.writerow(t.values())

    print(f"レポートをCSV出力しました: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Paper Trading Performance Report")
    parser.add_argument("--csv", action="store_true", help="CSVにもエクスポート")
    parser.add_argument("--json", action="store_true", help="JSONで出力")
    parser.add_argument("--db", default=os.getenv("DB_PATH", "tracker.db"), help="DBパス")
    args = parser.parse_args()

    loop = asyncio.new_event_loop()
    trades, summary = loop.run_until_complete(load_data(args.db))
    loop.close()

    if args.json:
        output = {"summary": summary, "trades": trades}
        print(json.dumps(output, indent=2, ensure_ascii=False, default=str))
        return

    console = Console()
    show_report(trades, summary, console)

    if args.csv:
        export_csv(trades, summary)


if __name__ == "__main__":
    main()
