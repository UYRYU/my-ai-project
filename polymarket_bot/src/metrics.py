"""Metrics collection and daily summary generation."""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime
from pathlib import Path

from .models import DailySummary, PaperPosition

logger = logging.getLogger("polymarket_bot")


class MetricsCollector:
    """Collect trade metrics and produce daily summaries."""

    def __init__(self, data_dir: str = "data") -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._all_positions: list[PaperPosition] = []

    def record_position(self, position: PaperPosition) -> None:
        self._all_positions.append(position)

    def record_positions(self, positions: list[PaperPosition]) -> None:
        self._all_positions.extend(positions)

    def generate_daily_summary(self, date_str: str | None = None) -> DailySummary:
        """Generate summary for a given date (default: today)."""
        if date_str is None:
            date_str = datetime.utcnow().strftime("%Y-%m-%d")

        day_positions = [
            p for p in self._all_positions
            if p.entry_time.strftime("%Y-%m-%d") == date_str
        ]

        total = len(day_positions)
        winners = [p for p in day_positions if p.pnl > 0]
        losers = [p for p in day_positions if p.pnl <= 0]

        total_pnl = sum(p.pnl for p in day_positions)
        win_rate = len(winners) / total * 100 if total > 0 else 0

        # Max drawdown (running PnL low point)
        max_dd = 0.0
        running_pnl = 0.0
        peak_pnl = 0.0
        for p in sorted(day_positions, key=lambda x: x.entry_time):
            running_pnl += p.pnl
            peak_pnl = max(peak_pnl, running_pnl)
            drawdown = peak_pnl - running_pnl
            max_dd = max(max_dd, drawdown)

        avg_hold = (
            sum(p.hold_time_sec for p in day_positions) / total
            if total > 0 else 0
        )

        summary = DailySummary(
            date=date_str,
            total_trades=total,
            winning_trades=len(winners),
            losing_trades=len(losers),
            total_pnl=round(total_pnl, 4),
            max_drawdown=round(max_dd, 4),
            avg_hold_time_sec=round(avg_hold, 1),
            win_rate=round(win_rate, 2),
            positions=[p.to_dict() for p in day_positions],
        )

        return summary

    def save_summary_json(self, summary: DailySummary) -> Path:
        """Save daily summary as JSON."""
        filepath = self.data_dir / f"summary_{summary.date}.json"
        data = {
            "date": summary.date,
            "total_trades": summary.total_trades,
            "winning_trades": summary.winning_trades,
            "losing_trades": summary.losing_trades,
            "total_pnl": summary.total_pnl,
            "max_drawdown": summary.max_drawdown,
            "avg_hold_time_sec": summary.avg_hold_time_sec,
            "win_rate": summary.win_rate,
            "positions": summary.positions,
        }
        filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Daily summary saved to %s", filepath)
        return filepath

    def save_trades_csv(self, date_str: str | None = None) -> Path:
        """Save all trades for the day as CSV."""
        if date_str is None:
            date_str = datetime.utcnow().strftime("%Y-%m-%d")

        filepath = self.data_dir / f"trades_{date_str}.csv"
        day_positions = [
            p for p in self._all_positions
            if p.entry_time.strftime("%Y-%m-%d") == date_str
        ]

        if not day_positions:
            logger.info("No trades to save for %s", date_str)
            return filepath

        fieldnames = list(day_positions[0].to_dict().keys())
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for pos in day_positions:
                writer.writerow(pos.to_dict())

        logger.info("Trades CSV saved to %s (%d trades)", filepath, len(day_positions))
        return filepath

    def print_summary(self, summary: DailySummary) -> None:
        """Print summary to terminal."""
        print("\n" + "=" * 60)
        print(f"  DAILY SUMMARY - {summary.date}")
        print("=" * 60)
        print(f"  Total trades:    {summary.total_trades}")
        print(f"  Winners:         {summary.winning_trades}")
        print(f"  Losers:          {summary.losing_trades}")
        print(f"  Win rate:        {summary.win_rate:.1f}%")
        print(f"  Total PnL:       ${summary.total_pnl:.4f}")
        print(f"  Max Drawdown:    ${summary.max_drawdown:.4f}")
        print(f"  Avg Hold Time:   {summary.avg_hold_time_sec:.0f}s")
        print("=" * 60 + "\n")
