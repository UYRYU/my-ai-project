"""検出フローをCSVに記録する"""

import csv
import os
from datetime import datetime

from scanner import OptionFlow
from classifier import classify

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
LOG_FILE = os.path.join(LOG_DIR, "flows.csv")

HEADERS = [
    "detected_at",
    "ticker",
    "contract",
    "strike",
    "expiration",
    "dte",
    "volume",
    "open_interest",
    "volume_oi_ratio",
    "premium",
    "side",
    "level",
]


def _ensure_log_file():
    """ログディレクトリとCSVヘッダーを初期化"""
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(HEADERS)


def log_flow(flow: OptionFlow):
    """1件のフローをCSVに追記"""
    _ensure_log_file()
    level = classify(flow)
    row = [
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        flow.ticker,
        flow.contract,
        flow.strike,
        flow.expiration,
        flow.dte,
        flow.volume,
        flow.open_interest,
        flow.volume_oi_ratio,
        flow.premium,
        flow.side,
        level,
    ]
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(row)


def log_flows(flows: list[OptionFlow]):
    """複数フローをまとめて記録"""
    for flow in flows:
        log_flow(flow)
    if flows:
        print(f"  📝 {len(flows)} flows saved to {LOG_FILE}")
