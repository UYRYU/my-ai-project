"""バックテスト - 記録したフローのシグナル後の値動きを検証"""

import csv
import sys
from datetime import datetime, timedelta

import requests

import config
from scanner import _get_headers

LOG_FILE = "logs/flows.csv"

# 検証期間（シグナル後N日間の値動き）
CHECK_DAYS = [1, 3, 5]


def _get_price_on_date(ticker: str, date: str) -> float | None:
    """指定日の終値を取得（Alpaca API）"""
    url = f"{config.ALPACA_DATA_URL}/v2/stocks/{ticker}/bars"
    params = {
        "timeframe": "1Day",
        "start": date,
        "limit": 1,
    }
    try:
        resp = requests.get(url, headers=_get_headers(), params=params, timeout=30)
        resp.raise_for_status()
        bars = resp.json().get("bars", [])
        if bars:
            return bars[0].get("c", 0)
    except requests.RequestException:
        pass
    return None


def _get_price_range(ticker: str, start: str, end: str) -> list[dict]:
    """期間の日足を取得"""
    url = f"{config.ALPACA_DATA_URL}/v2/stocks/{ticker}/bars"
    params = {
        "timeframe": "1Day",
        "start": start,
        "end": end,
        "limit": 30,
    }
    try:
        resp = requests.get(url, headers=_get_headers(), params=params, timeout=30)
        resp.raise_for_status()
        return resp.json().get("bars", [])
    except requests.RequestException:
        return []


def run_backtest():
    """CSV記録からバックテストを実行"""
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except FileNotFoundError:
        print("[ERROR] flows.csv が見つかりません。先にBotを実行してデータを蓄積してください。")
        sys.exit(1)

    if not rows:
        print("記録されたフローがありません。")
        return

    print(f"\n{'='*70}")
    print(f"  Backtest: {len(rows)} signals")
    print(f"  Checking price movement after {CHECK_DAYS} days")
    print(f"{'='*70}\n")

    results = {d: {"wins": 0, "losses": 0, "total_return": 0.0} for d in CHECK_DAYS}
    analyzed = 0

    for row in rows:
        detected_at = row.get("detected_at", "")
        ticker = row.get("ticker", "")
        level = row.get("level", "")
        strike = row.get("strike", "")
        premium = row.get("premium", "0")

        if not detected_at or not ticker:
            continue

        signal_date = datetime.strptime(detected_at, "%Y-%m-%d %H:%M:%S")
        max_check = max(CHECK_DAYS)
        end_date = signal_date + timedelta(days=max_check + 5)  # 土日分の余裕

        # シグナル日から指定期間の価格を取得
        bars = _get_price_range(
            ticker,
            signal_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d"),
        )

        if not bars:
            print(f"  ⏭️  {ticker} {detected_at} — price data unavailable")
            continue

        entry_price = bars[0].get("c", 0)
        if entry_price <= 0:
            continue

        analyzed += 1
        print(f"\n  📊 {ticker} | {strike}C | {level} | Premium: ${float(premium)/1000:.1f}K")
        print(f"     Signal: {detected_at} | Entry: ${entry_price:.2f}")

        for check_day in CHECK_DAYS:
            # check_day番目の取引日を取得
            if check_day < len(bars):
                exit_price = bars[check_day].get("c", 0)
                ret = (exit_price - entry_price) / entry_price * 100

                direction = "✅" if ret > 0 else "❌"
                print(f"     {check_day}D: ${exit_price:.2f} ({direction} {ret:+.2f}%)")

                if ret > 0:
                    results[check_day]["wins"] += 1
                else:
                    results[check_day]["losses"] += 1
                results[check_day]["total_return"] += ret
            else:
                print(f"     {check_day}D: — (not enough data yet)")

    # サマリー
    print(f"\n{'='*70}")
    print(f"  SUMMARY ({analyzed} signals analyzed)")
    print(f"{'='*70}")
    for d in CHECK_DAYS:
        r = results[d]
        total = r["wins"] + r["losses"]
        if total > 0:
            win_rate = r["wins"] / total * 100
            avg_ret = r["total_return"] / total
            print(f"  {d}D: Win Rate {win_rate:.1f}% ({r['wins']}/{total}) | Avg Return: {avg_ret:+.2f}%")
        else:
            print(f"  {d}D: No data yet")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    run_backtest()
