"""Paper取引のパフォーマンスレポートを生成する。

Usage:
    python report.py                # Richターミナル表示（全モデル）
    python report.py --v2-only      # v2_binary のみ集計 + CSV自動保存
    python report.py --period 24h   # 直近24時間のみ
    python report.py --period 7d    # 直近7日のみ
    python report.py --daily        # 日次レポートを reports/ に保存
    python report.py --csv          # CSVにもエクスポート
    python report.py --json         # JSON出力
    python report.py --equity-csv   # Equity curveをCSV出力
"""

import argparse
import asyncio
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from src.analytics import (
    avg_entry_price,
    band_best_worst,
    build_equity_curve,
    by_direction,
    by_entry_price_band,
    by_hour,
    by_market,
    by_signal_strength,
    check_v2_readiness,
    compute_edge_indicator,
    compute_summary,
    detect_warnings,
    filter_by_model,
    filter_by_period,
    live_block_reason,
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


def _show_edge_indicator(console: Console, trades: list[dict]) -> None:
    """Edge 指標パネルを表示する。"""
    edge = compute_edge_indicator(trades)
    if edge["count"] == 0:
        return

    edge_style = "green" if edge["has_edge"] else "red"
    edge_text = (
        f"[bold]実績勝率:[/bold]    [{edge_style}]{edge['actual_win_rate']}%[/{edge_style}]\n"
        f"[bold]期待勝率:[/bold]    {edge['expected_win_rate']}%  "
        f"[dim](entry_price加重平均)[/dim]\n"
        f"[bold]Edge:[/bold]         [{edge_style}]{edge['edge_pct']:+.1f}pp[/{edge_style}]  "
    )
    if edge["has_edge"]:
        edge_text += "[green bold]POSITIVE - シグナルにエッジあり[/green bold]"
    else:
        edge_text += "[red]NEGATIVE - シグナルのエッジ未確認[/red]"

    console.print(Panel(edge_text, title="Edge Indicator (勝率 vs 期待値)", style="cyan", expand=False))

    # 帯別 edge テーブル
    if edge["edge_per_band"]:
        table = Table(title="Entry Price Band Edge", show_lines=False, padding=(0, 1))
        table.add_column("Band", width=10)
        table.add_column("Count", justify="right", width=6)
        table.add_column("実績勝率", justify="right", width=10)
        table.add_column("期待勝率", justify="right", width=10)
        table.add_column("Edge", justify="right", width=10)

        for band, data in edge["edge_per_band"].items():
            e_style = "green" if data["edge_pct"] > 0 else "red"
            table.add_row(
                band,
                str(data["count"]),
                f"{data['actual_win_rate']}%",
                f"{data['expected_win_rate']}%",
                Text(f"{data['edge_pct']:+.1f}pp", style=e_style),
            )
        console.print(table)
    console.print()


def _show_band_best_worst(console: Console, trades: list[dict]) -> None:
    """帯別の best / worst トレードを表示する。"""
    bw = band_best_worst(trades)
    if not bw:
        return

    table = Table(title="Entry Price Band Best / Worst", show_lines=False, padding=(0, 1))
    table.add_column("Band", width=10)
    table.add_column("Count", justify="right", width=6)
    table.add_column("Best PnL", justify="right", width=10)
    table.add_column("Best Market", max_width=25)
    table.add_column("Worst PnL", justify="right", width=10)
    table.add_column("Worst Market", max_width=25)

    for band, data in bw.items():
        table.add_row(
            band,
            str(data["count"]),
            f"[green]${data['best_pnl']:+.2f}[/green]",
            data["best_market"],
            f"[red]${data['worst_pnl']:+.2f}[/red]",
            data["worst_market"],
        )

    console.print(table)
    console.print()


def _show_warnings(console: Console, trades: list[dict]) -> None:
    """edge マイナスの帯・マーケットを警告表示する。"""
    warns = detect_warnings(trades)
    if not warns:
        return

    lines = ["[bold red]以下のセグメントでエッジがマイナスです:[/bold red]\n"]
    for w in warns:
        lines.append(f"  [red]WARNING[/red]  {w}")

    console.print(Panel(
        "\n".join(lines),
        title="Edge Warnings",
        style="red",
        expand=False,
    ))
    console.print()


def _show_period_comparison(console: Console, trades: list[dict]) -> None:
    """直近24時間 / 直近7日 の成績を比較表示する。"""
    last_24h = filter_by_period(trades, hours=24)
    last_7d = filter_by_period(trades, days=7)

    periods = [
        ("直近24時間", last_24h),
        ("直近7日", last_7d),
        ("全期間", trades),
    ]

    table = Table(title="Period Comparison", show_lines=False, padding=(0, 1))
    table.add_column("期間", style="white", width=12)
    table.add_column("Count", justify="right", width=6)
    table.add_column("Win%", justify="right", width=7)
    table.add_column("Total PnL", justify="right", width=10)
    table.add_column("Avg PnL", justify="right", width=10)
    table.add_column("Edge", justify="right", width=10)
    table.add_column("PF", justify="right", width=8)

    for label, period_trades in periods:
        if not period_trades:
            table.add_row(label, "0", "-", "-", "-", "-", "-")
            continue
        s = compute_summary(period_trades)
        e = compute_edge_indicator(period_trades)
        wr_style = "green" if s["win_rate"] >= 50 else "red"
        pnl_style = "green" if s["total_pnl"] >= 0 else "red"
        e_style = "green" if e["edge_pct"] > 0 else "red"
        pf_str = f"{s['profit_factor']}" if s["profit_factor"] != float("inf") else "INF"
        table.add_row(
            label,
            str(s["count"]),
            Text(f"{s['win_rate']}%", style=wr_style),
            Text(f"${s['total_pnl']:+.2f}", style=pnl_style),
            f"${s['avg_pnl']:+.2f}",
            Text(f"{e['edge_pct']:+.1f}pp", style=e_style),
            pf_str,
        )

    console.print(table)
    console.print()


def _show_readiness_check(console: Console, all_trades: list[dict]) -> None:
    """v2 検証完了チェックパネルを表示する。"""
    ready = check_v2_readiness(all_trades)

    lines = [f"[bold]v2_binary トレード数: {ready['trade_count']}[/bold]\n"]

    for check in ready["checks"]:
        icon = "[green]PASS[/green]" if check["passed"] else "[red]FAIL[/red]"
        lines.append(f"  {icon}  {check['name']}  [dim]({check['value']})[/dim]")

    lines.append("")
    if ready["all_passed"]:
        lines.append(
            "[green bold]>>> 全条件クリア！案2 (edge パラメータ) へ進む準備ができています。 <<<[/green bold]"
        )
    elif ready["enough_trades"]:
        lines.append(
            "[yellow]100トレード到達済み。上記の未通過条件を確認してください。[/yellow]"
        )
    else:
        remaining = 100 - ready["trade_count"]
        lines.append(
            f"[dim]あと {remaining} トレードで100件到達。検証を継続してください。[/dim]"
        )

    border_style = "green" if ready["all_passed"] else "yellow"
    console.print(Panel(
        "\n".join(lines),
        title="v2 Binary Model - 案2(edge)移行判定",
        style=border_style,
        expand=False,
    ))
    console.print()


def show_report(
    trades: list[dict],
    signals_data: list[dict] | None,
    console: Console,
    v2_only: bool = False,
    period_label: str = "",
) -> None:
    """Richでレポートを表示する。"""
    console.print()

    # --- v2フィルタ ---
    all_trades_unfiltered = trades
    if v2_only:
        trades = filter_by_model(trades, "v2_binary")

    # --- ヘッダー ---
    filter_parts = []
    if v2_only:
        filter_parts.append("v2_binary ONLY")
    if period_label:
        filter_parts.append(period_label)
    filter_label = f" [{', '.join(filter_parts)}]" if filter_parts else ""

    banner = Text()
    banner.append(f"  Paper Trading Performance Report{filter_label}  ", style="bold white on magenta")
    console.print(Panel(banner, style="magenta", expand=False))
    console.print()

    # --- メインサマリー ---
    summary = compute_summary(trades)

    if summary["count"] == 0:
        console.print("  [yellow]Paper取引データがありません。[/yellow]")
        if v2_only:
            v1_count = len(filter_by_model(all_trades_unfiltered, "v1_random"))
            if v1_count:
                console.print(f"  [dim]v1_random のデータは {v1_count} 件あります。--v2-only を外すと表示されます。[/dim]")
        console.print("  python main.py でトラッカーを起動してデータを蓄積してください。")
        return

    # モデルバージョン検出
    model_versions = set(t.get("model_version", "unknown") for t in trades)
    model_label = ", ".join(sorted(model_versions)) if model_versions else "unknown"

    pnl_style = "green" if summary["total_pnl"] >= 0 else "red"
    wr_style = "green" if summary["win_rate"] >= 50 else "red"
    pf_str = f"{summary['profit_factor']}" if summary["profit_factor"] != float("inf") else "INF"
    avg_ep = avg_entry_price(trades)

    summary_text = (
        f"[bold]モデル:[/bold]          [magenta]{model_label}[/magenta]\n"
        f"[bold]総トレード数:[/bold]    {summary['count']}\n"
        f"[bold]勝敗:[/bold]            "
        f"[green]{summary['wins']}W[/green] / "
        f"[red]{summary['losses']}L[/red]\n"
        f"[bold]勝率:[/bold]            [{wr_style}]{summary['win_rate']}%[/{wr_style}]\n"
        f"[bold]平均 entry_price:[/bold] {avg_ep:.4f}\n"
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

    # --- 期間別比較 ---
    _show_period_comparison(console, trades)

    # --- Edge Indicator ---
    _show_edge_indicator(console, trades)

    # --- Entry Price 帯別成績 ---
    _add_group_table(console, "Entry Price Band Breakdown", by_entry_price_band(trades))

    # --- 帯別 best / worst ---
    _show_band_best_worst(console, trades)

    # --- マーケット別成績 ---
    _add_group_table(console, "Market Breakdown", by_market(trades))

    # --- 時間帯別成績 ---
    _add_group_table(console, "Hour Breakdown (UTC)", by_hour(trades))

    # --- シグナル強度別成績 ---
    _add_group_table(console, "Signal Strength Breakdown", by_signal_strength(trades, signals_data))

    # --- Direction別成績 ---
    _add_group_table(console, "Direction Breakdown", by_direction(trades))

    # --- 直近20トレード成績 ---
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

    # --- 警告表示 ---
    _show_warnings(console, trades)

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

    # --- v2 Readiness Check (常に全データから判定) ---
    _show_readiness_check(console, all_trades_unfiltered)

    # --- Live移行不可理由（1文） ---
    block = live_block_reason(all_trades_unfiltered)
    if block:
        console.print(Panel(
            f"[bold red]{block}[/bold red]",
            style="red",
            expand=False,
        ))
    else:
        console.print(Panel(
            "[bold green]全条件クリア。Live移行を検討できます。[/bold green]",
            style="green",
            expand=False,
        ))
    console.print()

    # --- 日次チェックリスト ---
    console.print(
        Panel(
            "[bold]毎日確認すべき5項目:[/bold]\n\n"
            "  [bold cyan]1.[/bold cyan] [bold]Edge[/bold]         実績勝率 > 期待勝率か？ (edge > 0pp)\n"
            "  [bold cyan]2.[/bold cyan] [bold]直近24h PnL[/bold]  今日の損益はプラスか？ 急変はないか？\n"
            "  [bold cyan]3.[/bold cyan] [bold]Warnings[/bold]     マイナスedgeの帯・マーケットが増えていないか？\n"
            "  [bold cyan]4.[/bold cyan] [bold]Profit Factor[/bold] PF > 1.0 を維持しているか？\n"
            "  [bold cyan]5.[/bold cyan] [bold]Drawdown[/bold]     最大DDが投入資金の20%を超えていないか？",
            title="Daily Checklist",
            style="blue",
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

        # Edge Indicator
        edge = compute_edge_indicator(trades)
        writer.writerow(["=== Edge Indicator ==="])
        for key, val in edge.items():
            if key != "edge_per_band":
                writer.writerow([key, val])
        writer.writerow([])

        # Entry Price 帯別
        writer.writerow(["=== Entry Price Band Breakdown ==="])
        for name, stats in by_entry_price_band(trades).items():
            writer.writerow([name] + [f"{k}={v}" for k, v in stats.items()])
        writer.writerow([])

        # Band Best / Worst
        writer.writerow(["=== Band Best / Worst ==="])
        for name, data in band_best_worst(trades).items():
            writer.writerow([name] + [f"{k}={v}" for k, v in data.items()])
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

        # Warnings
        warns = detect_warnings(trades)
        if warns:
            writer.writerow(["=== Warnings ==="])
            for w in warns:
                writer.writerow([w])
            writer.writerow([])

        # Live block reason
        block = live_block_reason(trades)
        writer.writerow(["=== Live Status ==="])
        writer.writerow([block if block else "Live移行可能"])
        writer.writerow([])

        # 取引詳細
        writer.writerow(["=== Trade Details ==="])
        if trades:
            writer.writerow(trades[0].keys())
            for t in trades:
                writer.writerow(t.values())

    print(f"レポートをCSV出力しました: {path}")


def save_daily_report(trades: list[dict], signals_data: list[dict] | None) -> str:
    """日次レポートを reports/ ディレクトリに保存する。"""
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    csv_path = reports_dir / f"report_{today}.csv"
    json_path = reports_dir / f"report_{today}.json"

    # CSV保存
    export_csv(trades, signals_data, str(csv_path))

    # JSON保存
    summary = compute_summary(trades)
    edge = compute_edge_indicator(trades)
    readiness = check_v2_readiness(trades)
    output = {
        "date": today,
        "summary": summary,
        "avg_entry_price": avg_entry_price(trades),
        "edge_indicator": edge,
        "v2_readiness": readiness,
        "warnings": detect_warnings(trades),
        "live_block_reason": live_block_reason(trades),
        "by_entry_price_band": by_entry_price_band(trades),
        "by_market": by_market(trades),
        "by_direction": by_direction(trades),
        "by_hour": by_hour(trades),
        "band_best_worst": band_best_worst(trades),
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)

    print(f"日次レポート保存: {csv_path}, {json_path}")
    return str(csv_path)


def _parse_period(period_str: str) -> tuple[int | None, int | None, str]:
    """'24h' or '7d' をパースして (hours, days, label) を返す。"""
    if not period_str:
        return None, None, ""
    s = period_str.strip().lower()
    if s.endswith("h"):
        hours = int(s[:-1])
        return hours, None, f"直近{hours}時間"
    elif s.endswith("d"):
        days = int(s[:-1])
        return None, days, f"直近{days}日"
    else:
        return None, None, ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Paper Trading Performance Report")
    parser.add_argument("--v2-only", action="store_true", help="v2_binary のみ集計")
    parser.add_argument("--period", default="", help="期間フィルタ (例: 24h, 7d)")
    parser.add_argument("--daily", action="store_true", help="日次レポートを reports/ に保存")
    parser.add_argument("--csv", action="store_true", help="CSVにもエクスポート")
    parser.add_argument("--json", action="store_true", help="JSONで出力")
    parser.add_argument("--equity-csv", action="store_true", help="Equity curveをCSV出力")
    parser.add_argument("--db", default=os.getenv("DB_PATH", "tracker.db"), help="DBパス")
    args = parser.parse_args()

    loop = asyncio.new_event_loop()
    trades, signals_data = loop.run_until_complete(load_data(args.db))
    loop.close()

    # v2フィルタ
    filtered = filter_by_model(trades, "v2_binary") if args.v2_only else trades

    # 期間フィルタ
    hours, days, period_label = _parse_period(args.period)
    if hours is not None or days is not None:
        filtered = filter_by_period(filtered, hours=hours, days=days)

    if args.json:
        summary = compute_summary(filtered)
        edge = compute_edge_indicator(filtered)
        readiness = check_v2_readiness(trades)  # 全データから判定
        output = {
            "filter": "v2_binary" if args.v2_only else "all",
            "period": period_label or "all",
            "summary": summary,
            "avg_entry_price": avg_entry_price(filtered),
            "edge_indicator": edge,
            "v2_readiness": readiness,
            "warnings": detect_warnings(filtered),
            "live_block_reason": live_block_reason(trades),
            "by_entry_price_band": by_entry_price_band(filtered),
            "band_best_worst": band_best_worst(filtered),
            "by_market": by_market(filtered),
            "by_direction": by_direction(filtered),
            "by_hour": by_hour(filtered),
            "by_signal_strength": by_signal_strength(filtered, signals_data),
            "recent_20": recent_n(filtered, 20),
            "equity_curve": build_equity_curve(filtered),
            "trades": filtered,
        }
        print(json.dumps(output, indent=2, ensure_ascii=False, default=str))
        return

    console = Console()
    show_report(trades, signals_data, console, v2_only=args.v2_only, period_label=period_label)

    # --v2-only の場合は自動的に paper_report_v2.csv に保存
    if args.v2_only and filtered:
        export_csv(filtered, signals_data, "paper_report_v2.csv")

    if args.csv:
        csv_name = "paper_report_v2.csv" if args.v2_only else "paper_report.csv"
        export_csv(filtered, signals_data, csv_name)

    if args.equity_csv:
        export_equity_csv(filtered)

    if args.daily:
        save_daily_report(filtered, signals_data)


if __name__ == "__main__":
    main()
