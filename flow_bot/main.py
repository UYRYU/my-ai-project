"""Unusual Options Flow Bot - メインエントリーポイント"""

import time
import sys
from datetime import datetime

import config
from scanner import scan_all
from classifier import classify, format_alert


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


def main():
    """メインループ"""
    if not config.POLYGON_API_KEY:
        print("\033[31m[ERROR] POLYGON_API_KEY が設定されていません。\033[0m")
        print("  export POLYGON_API_KEY='your-api-key'")
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
