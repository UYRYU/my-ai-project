"""Dukascopy から GBPJPY/EURJPY/USDJPY M1 2年分をダウンロード"""

import os
import sys
from datetime import datetime, timedelta
import pandas as pd
import dukascopy_python as dk

PAIRS = ["GBPJPY", "EURJPY", "USDJPY"]
DK_NAMES = {"GBPJPY": "GBP/JPY", "EURJPY": "EUR/JPY", "USDJPY": "USD/JPY"}
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "raw")
os.makedirs(OUTPUT_DIR, exist_ok=True)

START = datetime(2023, 4, 1)
END = datetime(2025, 4, 1)


def download_pair(pair: str):
    dk_name = DK_NAMES[pair]
    out_path = os.path.join(OUTPUT_DIR, f"{pair}_M1.csv")
    backup_path = out_path + ".bak"

    # 既存データをバックアップ
    if os.path.exists(out_path):
        os.rename(out_path, backup_path)
        print(f"  既存データをバックアップ: {backup_path}")

    all_dfs = []
    current = START

    while current < END:
        # 1ヶ月ずつダウンロード (API制限対策)
        next_month = current + timedelta(days=32)
        next_month = next_month.replace(day=1)
        if next_month > END:
            next_month = END

        month_label = current.strftime("%Y-%m")
        print(f"  {pair} {month_label}...", end=" ", flush=True)

        try:
            df = dk.fetch(
                instrument=dk_name,
                interval=dk.INTERVAL_MIN_1,
                offer_side=dk.OFFER_SIDE_BID,
                start=current,
                end=next_month,
                max_retries=5,
            )
            if df is not None and len(df) > 0:
                print(f"{len(df)} bars")
                all_dfs.append(df)
            else:
                print("0 bars (skip)")
        except Exception as e:
            print(f"ERROR: {e}")

        current = next_month

    if not all_dfs:
        print(f"  {pair}: データ取得失敗")
        # バックアップを復元
        if os.path.exists(backup_path):
            os.rename(backup_path, out_path)
        return False

    # 結合・整形
    full = pd.concat(all_dfs, ignore_index=True)
    full = full.sort_values("timestamp" if "timestamp" in full.columns else full.columns[0]).reset_index(drop=True)

    # カラム名を標準化
    col_map = {}
    for c in full.columns:
        cl = c.lower()
        if "time" in cl or "date" in cl:
            col_map[c] = "timestamp"
        elif cl == "open" or cl == "o":
            col_map[c] = "open"
        elif cl == "high" or cl == "h":
            col_map[c] = "high"
        elif cl == "low" or cl == "l":
            col_map[c] = "low"
        elif cl == "close" or cl == "c":
            col_map[c] = "close"
        elif "vol" in cl:
            col_map[c] = "volume"
    full = full.rename(columns=col_map)

    # 必須カラム確認
    for need in ["timestamp", "open", "high", "low", "close"]:
        if need not in full.columns:
            print(f"  {pair}: カラム '{need}' が見つかりません。columns={list(full.columns)}")
            if os.path.exists(backup_path):
                os.rename(backup_path, out_path)
            return False

    if "volume" not in full.columns:
        full["volume"] = 0

    full = full[["timestamp", "open", "high", "low", "close", "volume"]]
    full = full.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

    full.to_csv(out_path, index=False)
    print(f"  {pair}: {len(full)} bars 保存 → {out_path}")
    print(f"  期間: {full['timestamp'].iloc[0]} 〜 {full['timestamp'].iloc[-1]}")

    # バックアップ削除
    if os.path.exists(backup_path):
        os.remove(backup_path)

    return True


def main():
    print("=" * 60)
    print("  Dukascopy M1データダウンロード (2年分)")
    print(f"  期間: {START.date()} 〜 {END.date()}")
    print(f"  通貨: {', '.join(PAIRS)}")
    print("=" * 60)

    for pair in PAIRS:
        print(f"\n--- {pair} ---")
        ok = download_pair(pair)
        if not ok:
            print(f"  {pair} のダウンロードに失敗しました")

    print("\n" + "=" * 60)
    print("  完了。検証を実行するには:")
    print("  python main.py --validate")
    print("=" * 60)


if __name__ == "__main__":
    main()
