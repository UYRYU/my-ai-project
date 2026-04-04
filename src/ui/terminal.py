"""Richベースのターミナル表示モジュール。"""

from datetime import datetime, timezone

from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from src.collector.base import Trade
from src.processor.signal_detector import Signal


class TerminalUI:
    def __init__(self) -> None:
        self.console = Console()

    def show_banner(self) -> None:
        banner = Text()
        banner.append("  Polymarket Wallet Tracker Terminal  ", style="bold white on blue")
        self.console.print()
        self.console.print(Panel(banner, style="blue", expand=False))
        self.console.print()

    def show_wallets(self, wallets: list) -> None:
        table = Table(title="監視ウォレット一覧", show_lines=True)
        table.add_column("#", style="dim", width=4)
        table.add_column("Label", style="cyan")
        table.add_column("Address", style="green")
        table.add_column("Note", style="dim")

        for i, w in enumerate(wallets, 1):
            table.add_row(
                str(i),
                w.label,
                f"{w.address[:10]}...{w.address[-6:]}",
                w.note,
            )
        self.console.print(table)
        self.console.print()

    def show_trades(self, trades: list[Trade], cycle: int) -> None:
        if not trades:
            self.console.print(
                f"  [dim]Cycle #{cycle}: 新しい取引なし[/dim]"
            )
            return

        table = Table(
            title=f"取得した取引 (Cycle #{cycle})",
            show_lines=False,
            padding=(0, 1),
        )
        table.add_column("Time", style="dim", width=12)
        table.add_column("Wallet", style="cyan", width=14)
        table.add_column("Market", style="white", max_width=35)
        table.add_column("Direction", width=10)
        table.add_column("Amount", style="yellow", justify="right", width=10)
        table.add_column("Price", justify="right", width=8)

        for t in trades[-20:]:  # 最新20件
            direction_style = "green" if "Buy" in t.direction else "red"
            table.add_row(
                t.timestamp.strftime("%H:%M:%S"),
                f"{t.wallet_address[:6]}..{t.wallet_address[-4:]}",
                t.market_title[:35],
                Text(t.direction, style=direction_style),
                f"${t.amount_usdc:,.0f}",
                f"{t.price:.2%}",
            )
        self.console.print(table)

    def show_signals(self, signals: list[Signal]) -> None:
        if not signals:
            return

        for signal in signals:
            strength_style = "bold red" if signal.is_strong else "bold yellow"
            strength_icon = "!!!" if signal.is_strong else "!"

            panel_content = (
                f"[bold]Market:[/bold] {signal.market_title}\n"
                f"[bold]Direction:[/bold] {signal.direction}\n"
                f"[bold]Wallets:[/bold] {signal.wallet_count}\n"
                f"[bold]Total Amount:[/bold] ${signal.total_amount_usdc:,.2f}\n"
                f"[bold]Avg Price:[/bold] {signal.avg_price:.2%}\n"
                f"[bold]Window:[/bold] "
                f"{signal.first_trade_time.strftime('%H:%M:%S')} - "
                f"{signal.last_trade_time.strftime('%H:%M:%S')}\n"
                f"[bold]Wallets:[/bold] "
                + ", ".join(f"{w[:8]}..." for w in signal.wallets)
            )

            self.console.print()
            self.console.print(
                Panel(
                    panel_content,
                    title=f"{strength_icon} SIGNAL [{signal.strength_label}] {strength_icon}",
                    style=strength_style,
                    expand=False,
                )
            )

    def show_execution_status(self, exec_stats: dict) -> None:
        """Executor の統計情報を表示する。"""
        mode = exec_stats.get("mode", "N/A")
        mode_style = {
            "PAPER": "bold cyan",
            "LIVE": "bold red",
            "DRY-RUN": "bold yellow",
        }.get(mode, "dim")

        risk = exec_stats.get("risk", {})
        halted = risk.get("halted", False)
        halt_indicator = " [bold red][HALTED][/bold red]" if halted else ""

        content = (
            f"[bold]Mode:[/bold] [{mode_style}]{mode}[/{mode_style}]{halt_indicator}\n"
            f"[bold]Orders:[/bold] {exec_stats.get('total_orders', 0)} "
            f"(Filled: {exec_stats.get('total_fills', 0)}, "
            f"Rejected: {exec_stats.get('total_rejects', 0)})\n"
            f"[bold]Daily Loss:[/bold] "
            f"${risk.get('daily_loss', 0):.2f} / ${risk.get('max_daily_loss', 0):.2f}\n"
            f"[bold]PnL:[/bold] ${exec_stats.get('total_pnl', 0):.2f}"
        )

        self.console.print(
            Panel(content, title="Execution Status", style="cyan", expand=False)
        )

    def show_order_result(self, order) -> None:
        """個別の注文結果を表示する。"""
        status = order.status.value.upper()
        if status == "FILLED":
            style = "green"
        elif status == "REJECTED":
            style = "yellow"
        else:
            style = "red"

        reason = f" ({order.reject_reason})" if order.reject_reason else ""
        self.console.print(
            f"  [{style}][{order.mode.value.upper()}] "
            f"{status}: {order.market_title[:30]} "
            f"{order.direction} ${order.amount_usdc:.2f}{reason}[/{style}]"
        )

    def show_status(
        self, cycle: int, trade_count: int, signal_count: int, next_poll: int,
        order_count: int = 0, fill_count: int = 0,
    ) -> None:
        self.console.print()
        self.console.print(
            f"  [dim]--- Cycle #{cycle} 完了 | "
            f"累計取引: {trade_count} | 累計シグナル: {signal_count} | "
            f"発注: {order_count} | 約定: {fill_count} | "
            f"次回取得まで {next_poll}秒 ---[/dim]"
        )
        self.console.print()

    def show_error(self, message: str) -> None:
        self.console.print(f"  [bold red]ERROR:[/bold red] {message}")

    def show_info(self, message: str) -> None:
        self.console.print(f"  [bold blue]INFO:[/bold blue] {message}")
