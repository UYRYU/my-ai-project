"""Unusual Options Flow Bot - メインエントリーポイント"""

import time
import sys
from datetime import datetime

import config
from scanner import scan_all
from classifier import classify, format_alert
from logger import log_flows


def print_banner():
    """起動バナー表示"""
    print("\033[1m")
    print("=" * 60)
    print("  Unusual Options Flow Bot")
    print("  Monitoring: " + ", ".join(config.WATCHLIST))
    print(f"  Filters: Vol/OI >= {config.MIN_VOLUME_OI_RATIO}x | "
          f"Premium >= ${config.MIN_PREMIUM_USD/1000:.0f}K | "
          f"DTE <= {config.MAX_DTE} | CALL only")
    print("=" * 60)
    print("\033[0m")


def run_scan():
    """1回のスキャンを実行し、検出結果を表示"""
    now = datetime.now().strftime("%H:%M:%S")
    print(f"\n[{now}] Scanning {len(config.WATCHLIST)} tickers...")

    flows = scan_all()

    if not flows:
        print(f"[{now}] No unusual activity detected.")
        return

    # プレミアム降順でソート
    flows.sort(key=lambda f: f.premium, reverse=True)

    print(f"\n[{now}] 🚨 {len(flows)} unusual flow(s) detected!")
    for flow in flows:
        level = classify(flow)
        print(format_alert(flow, level))

    # CSVに記録
    log_flows(flows)


def main():
    """メインループ"""
    if not config.ALPACA_API_KEY or not config.ALPACA_SECRET_KEY:
        print("\033[31m[ERROR] Alpaca APIキーが設定されていません。\033[0m")
        print("  export ALPACA_API_KEY='your-key'")
        print("  export ALPACA_SECRET_KEY='your-secret'")
        sys.exit(1)

    print_banner()

    try:
        while True:
            run_scan()
            print(f"\n⏳ Next scan in {config.SCAN_INTERVAL}s... (Ctrl+C to stop)")
            time.sleep(config.SCAN_INTERVAL)
    except KeyboardInterrupt:
        print("\n\n👋 Bot stopped.")
        sys.exit(0)


if __name__ == "__main__":
    main()
