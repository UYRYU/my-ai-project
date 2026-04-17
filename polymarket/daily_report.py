"""
Polymarket Tracker - 日次レポート
毎日のペーパートレード成績をファイルに記録する。
Windows放置時でもログとして残るので、いつでも確認できる。

出力先: data/daily_reports/YYYY-MM-DD.txt
"""

import json
import os
from datetime import datetime, timezone

from loguru import logger

import risk

REPORTS_DIR = "data/daily_reports"
PAPER_TRADES_PATH = "data/paper_trades.json"


def _load_trades() -> list:
    if not os.path.exists(PAPER_TRADES_PATH):
        return []
    try:
        with open(PAPER_TRADES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def generate_report(date_str: str = None) -> str:
    """
    指定日 (YYYY-MM-DD) のレポートを生成する。
    省略時は今日。
    """
    if not date_str:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    trades = _load_trades()
    today_closed = [
        t for t in trades
        if t.get("status") == "closed"
        and (t.get("closed_date", "") or "").startswith(date_str)
    ]
    today_opened = [
        t for t in trades
        if (t.get("opened_at", "") or "").startswith(date_str)
    ]

    total = [t for t in trades if t.get("status") == "closed"]
    total_pnl = sum(t.get("pnl", 0) for t in total)
    today_pnl = sum(t.get("pnl", 0) for t in today_closed)
    today_wins = sum(1 for t in today_closed if t.get("result") == 1)
    today_losses = sum(1 for t in today_closed if t.get("result") == 0)
    balance = risk.BANKROLL + total_pnl

    lines = []
    lines.append("=" * 60)
    lines.append(f" Polymarket ペーパートレード 日次レポート")
    lines.append(f" 日付: {date_str} (UTC)")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f" 本日エントリー: {len(today_opened)} 件")
    lines.append(f" 本日決着     : {len(today_closed)} 件 (勝 {today_wins} / 負 {today_losses})")
    if today_closed:
        wr = today_wins / len(today_closed) * 100
        lines.append(f" 本日勝率     : {wr:.1f}%")
    lines.append(f" 本日損益     : ${today_pnl:+.2f}")
    lines.append("")
    lines.append(" -- 累計 --")
    lines.append(f" 総トレード数 : {len(trades)}")
    lines.append(f" 決着件数     : {len(total)}")
    if total:
        total_wr = sum(1 for t in total if t.get("result") == 1) / len(total) * 100
        lines.append(f" 累計勝率     : {total_wr:.1f}%")
    lines.append(f" 累計損益     : ${total_pnl:+.2f}")
    lines.append(f" 仮想残高     : ${balance:.2f} (開始 ${risk.BANKROLL})")
    lines.append("")

    # 本日の決着トレード
    if today_closed:
        lines.append(" -- 本日の決着詳細 --")
        for t in sorted(today_closed, key=lambda x: x.get("closed_date", "")):
            mark = "✓" if t.get("result") == 1 else "✗"
            lines.append(
                f"  {mark} {t.get('outcome', '')[:18]:<18} @ {t.get('odds', 0):.3f} "
                f"${t.get('size', 0):>5.2f} → ${t.get('pnl', 0):+.2f} | "
                f"{t.get('market_title', '')[:45]}"
            )
        lines.append("")

    # 自動調整状況
    try:
        from auto_tune import load_blocked_bands, load_blocked_sports
        from trader_stats import load_blacklist, load_whitelist
        lines.append(" -- 戦略の自動調整状況 --")
        lines.append(f"  除外オッズ帯: {load_blocked_bands() or 'なし'}")
        lines.append(f"  除外スポーツ: {load_blocked_sports() or 'なし'}")
        lines.append(f"  ブラックリスト: {len(load_blacklist())} 人")
        lines.append(f"  ホワイトリスト: {len(load_whitelist())} 人")
        lines.append("")
    except Exception:
        pass

    lines.append("=" * 60)

    report_text = "\n".join(lines)

    # ファイルに保存
    os.makedirs(REPORTS_DIR, exist_ok=True)
    path = os.path.join(REPORTS_DIR, f"{date_str}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(report_text)

    logger.info(f"[daily_report] {path} に保存")
    return report_text


def print_today() -> None:
    """今日のレポートを生成してコンソールに表示"""
    text = generate_report()
    print("\n" + text + "\n")


if __name__ == "__main__":
    print_today()
