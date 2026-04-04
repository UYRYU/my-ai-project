"""Paper取引のパフォーマンスレポートを生成する。

Usage:
    python report.py              # Richターミナル表示
    python report.py --csv        # CSVにもエクスポート
    python report.py --json       # JSON出力
    python report.py --equity-csv # Equity curveをCSV出力
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

from src.analytics import (
    build_equity_curve,
    by_direction,
    by_hour,
    by_market,
    by_signal_strength,
    compute_summary,
    recent_n,
)

load_dotenv()

# Windows asyncio 互換性
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def load_data(db_path: str) -> tuple[list[dict], list[dict] | None]:
    """DBからPaper取引データとシグナルデータを読み込む。"""
    import aiosqlite

    db = await aiosqlite.connect(db_path)

    # paper_tradesテーブルの存在確認
    cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='paper_trades'"
    )
    if not await cursor.fetchone():
        await db.close()
        return [], None

    # 全取引取得
    db.row_factory = aiosqlite.Row
    cursor = await db.execute(
        "SELECT * FROM paper_trades ORDER BY created_at ASC"
    )
    rows = await cursor.fetchall()
    trades = [dict(row) for row in rows]

    # シグナルデータ取得（存在する場合）
    signals_data = None
    cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='signals'"
    )
    if await cursor.fetchone():
        cursor = await db.execute("SELECT * FROM signals")
        sig_rows = await cursor.fetchall()
        signals_data = [dict(r) for r in sig_rows]

    await db.close()
    return trades, signals_data


def _add_group_table(console: Console, title: str, data: dict[str, dict]) -> None:
    """グループ別統計をRichテーブルで表示する。"""
    if not data:
        console.print(f"  [dim]{title}: データなし[/dim]")
        return

    table = Table(title=title, show_lines=False, padding=(0, 1))
    table.add_column("Group", style="white", max_width=35)
    table.add_column("Count", justify="right", width=6)
    table.add_column("W/L", justify="right", width=8)
    table.add_column("Win%", justify="right", width=7)
    table.add_column("Total PnL", justify="right", width=10)
    table.add_column("Avg PnL", justify="right", width=10)
    table.add_column("Avg Win", justify="right", width=10)
    table.add_column("Avg Loss", justify="right", width=10)

    for group_name, stats in data.items():
        wr_style = "green" if stats["win_rate"] >= 50 else "red"
        pnl_style = "green" if stats["total_pnl"] >= 0 else "red"
        table.add_row(
            str(group_name)[:35],
            str(stats["count"]),
            f"{stats['wins']}W/{stats['losses']}L",
            Text(f"{stats['win_rate']}%", style=wr_style),
            Text(f"${stats['total_pnl']:+.2f}", style=pnl_style),
            f"${stats['avg_pnl']:+.2f}",
            f"[green]${stats['avg_win']:+.2f}[/green]",
            f"[red]${stats['avg_loss']:+.2f}[/red]",
        )

    console.print(table)
    console.print()


def show_report(trades: list[dict], signals_data: list[dict] | None, console: Console) -> None:
    """Richでレポートを表示する。"""
    console.print()

    # --- ヘッダー ---
    banner = Text()
    banner.append("  Paper Trading Performance Report  ", style="bold white on magenta")
    console.print(Panel(banner, style="magenta", expand=False))
    console.print()

    # --- メインサマリー ---
    summary = compute_summary(trades)

    if summary["count"] == 0:
        console.print("  [yellow]Paper取引データがありません。[/yellow]")
        console.print("  python main.py でトラッカーを起動してデータを蓄積してください。")
        return

    # モデルバージョン検出
    model_versions = set(t.get("model_version", "unknown") for t in trades)
    model_label = ", ".join(sorted(model_versions)) if model_versions else "unknown"

    pnl_style = "green" if summary["total_pnl"] >= 0 else "red"
    wr_style = "green" if summary["win_rate"] >= 50 else "red"
    pf_str = f"{summary['profit_factor']}" if summary["profit_factor"] != float("inf") else "∞"

    summary_text = (
        f"[bold]モデル:[/bold]          [magenta]{model_label}[/magenta]\n"
        f"[bold]総トレード数:[/bold]    {summary['count']}\n"
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
        f"[bold]平均保有時間:[/bold]    {summary['avg_holding_minutes']}分\n"
        f"[bold]最大DD:[/bold]          [red]${summary['max_drawdown']:.2f}[/red] ({summary['max_drawdown_pct']}%)\n"
        f"[bold]Profit Factor:[/bold]   {pf_str}"
    )
    console.print(Panel(summary_text, title="Performance Summary", style="cyan", expand=False))
    console.print()

    # --- 1. マーケット別成績 ---
    _add_group_table(console, "Market Breakdown", by_market(trades))

    # --- 2. 時間帯別成績 ---
    _add_group_table(console, "Hour Breakdown (UTC)", by_hour(trades))

    # --- 3. シグナル強度別成績 ---
    _add_group_table(console, "Signal Strength Breakdown", by_signal_strength(trades, signals_data))

    # --- 4. Direction別成績 ---
    _add_group_table(console, "Direction Breakdown", by_direction(trades))

    # --- 5. 直近20トレード成績 ---
    recent = recent_n(trades, 20)
    recent_wr_style = "green" if recent["win_rate"] >= 50 else "red"
    recent_pnl_style = "green" if recent["total_pnl"] >= 0 else "red"
    recent_text = (
        f"[bold]件数:[/bold] {recent['count']}  "
        f"[bold]勝率:[/bold] [{recent_wr_style}]{recent['win_rate']}%[/{recent_wr_style}]  "
        f"[bold]PnL:[/bold] [{recent_pnl_style}]${recent['total_pnl']:+.2f}[/{recent_pnl_style}]  "
        f"[bold]Avg:[/bold] ${recent['avg_pnl']:+.2f}"
    )
    console.print(Panel(recent_text, title="Recent 20 Trades", style="blue", expand=False))
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
    table.add_column("Model", style="dim", width=10)

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
            t.get("model_version", "?"),
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
            "  6. 異なる時間帯・マーケットで安定\n"
            "  7. 最大ドローダウン < 投入資金の20%\n"
            "  8. Profit Factor > 1.2\n\n"
            "[dim]全基準を満たすまでは live に移行しないでください。[/dim]",
            title="Live移行判断基準",
            style="yellow",
            expand=False,
        )
    )


def export_equity_csv(trades: list[dict], path: str = "equity_curve.csv") -> None:
    """Equity curveをCSVに出力する。"""
    curve = build_equity_curve(trades)
    if not curve:
        print("Equity curveデータがありません。")
        return

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=curve[0].keys())
        writer.writeheader()
        writer.writerows(curve)

    print(f"Equity curveをCSV出力しました: {path}")


def export_csv(trades: list[dict], signals_data: list[dict] | None, path: str = "paper_report.csv") -> None:
    """レポートをCSVに出力する。"""
    summary = compute_summary(trades)

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        # サマリーセクション
        writer.writerow(["=== Performance Summary ==="])
        for key, val in summary.items():
            writer.writerow([key, val])
        writer.writerow([])

        # マーケット別
        writer.writerow(["=== Market Breakdown ==="])
        for name, stats in by_market(trades).items():
            writer.writerow([name] + [f"{k}={v}" for k, v in stats.items()])
        writer.writerow([])

        # Direction別
        writer.writerow(["=== Direction Breakdown ==="])
        for name, stats in by_direction(trades).items():
            writer.writerow([name] + [f"{k}={v}" for k, v in stats.items()])
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
    parser.add_argument("--equity-csv", action="store_true", help="Equity curveをCSV出力")
    parser.add_argument("--db", default=os.getenv("DB_PATH", "tracker.db"), help="DBパス")
    args = parser.parse_args()

    loop = asyncio.new_event_loop()
    trades, signals_data = loop.run_until_complete(load_data(args.db))
    loop.close()

    if args.json:
        summary = compute_summary(trades)
        output = {
            "summary": summary,
            "by_market": by_market(trades),
            "by_direction": by_direction(trades),
            "by_hour": by_hour(trades),
            "by_signal_strength": by_signal_strength(trades, signals_data),
            "recent_20": recent_n(trades, 20),
            "equity_curve": build_equity_curve(trades),
            "trades": trades,
        }
        print(json.dumps(output, indent=2, ensure_ascii=False, default=str))
        return

    console = Console()
    show_report(trades, signals_data, console)

    if args.csv:
        export_csv(trades, signals_data)

    if args.equity_csv:
        export_equity_csv(trades)


if __name__ == "__main__":
    main()
