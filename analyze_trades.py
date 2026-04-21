"""
MT5 取引履歴 Magic Number別分析
使い方: python3 analyze_trades.py <CSVファイルパス>
"""

import sys
import csv
import os
from collections import defaultdict

USDJPY = 158.0  # 概算レート

def parse_csv(filepath):
    trades = []
    encodings = ["utf-8", "utf-8-sig", "shift_jis", "cp932"]
    for enc in encodings:
        try:
            with open(filepath, encoding=enc) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    trades.append(row)
            break
        except:
            continue
    return trades

def find_col(row, candidates):
    for k in row.keys():
        for c in candidates:
            if c.lower() in k.lower():
                return k
    return None

def analyze(filepath):
    trades = parse_csv(filepath)
    if not trades:
        print("CSVを読み込めませんでした")
        return

    sample = trades[0]
    col_magic  = find_col(sample, ["magic", "マジック"])
    col_profit = find_col(sample, ["profit", "損益", "利益"])
    col_type   = find_col(sample, ["type", "タイプ"])
    col_symbol = find_col(sample, ["symbol", "銘柄", "item"])
    col_ticket = find_col(sample, ["ticket", "チケット"])
    col_time   = find_col(sample, ["close time", "決済時間", "time"])

    print(f"列検出: magic={col_magic} profit={col_profit} type={col_type}")

    groups = defaultdict(list)
    for row in trades:
        try:
            profit = float(str(row.get(col_profit, "0")).replace(",", "").replace(" ", "") or 0)
        except:
            continue
        magic = row.get(col_magic, "不明").strip() if col_magic else "不明"
        trade_type = row.get(col_type, "").strip().lower() if col_type else ""
        if trade_type in ["buy", "sell", "買い", "売り", "0", "1"]:
            groups[magic].append(profit)

    if not groups:
        print("\n取引データが見つかりませんでした。列名を確認してください。")
        print("列一覧:", list(sample.keys()))
        return

    print()
    print("=" * 62)
    print("  Magic Number 別 パフォーマンス比較")
    print("=" * 62)
    print(f"  {'Magic':<14} {'件数':>5} {'勝':>4} {'負':>4} {'勝率':>7} {'純損益':>10} {'PF':>6} {'avg勝':>8} {'avg負':>8}")
    print("-" * 62)

    for magic, profits in sorted(groups.items()):
        import numpy as np
        p = [x for x in profits if x > 0]
        l = [x for x in profits if x <= 0]
        n = len(profits)
        nw = len(p)
        nl = len(l)
        wr = nw / n * 100 if n else 0
        net = sum(profits)
        pf  = abs(sum(p) / sum(l)) if l and sum(l) != 0 else float("inf")
        ag  = sum(p) / nw if nw else 0
        al  = sum(l) / nl if nl else 0

        label = {
            "20240101": "①トレールあり",
            "20240102": "②トレールなし",
        }.get(magic, f"Magic:{magic}")

        print(f"  {label:<14} {n:>5} {nw:>4} {nl:>4} {wr:>6.1f}% ¥{net:>+8.0f} {pf:>6.2f} ¥{ag:>+7.0f} ¥{al:>+7.0f}")

    print("=" * 62)
    print()

    # 総合
    all_profits = [p for ps in groups.values() for p in ps]
    p = [x for x in all_profits if x > 0]
    l = [x for x in all_profits if x <= 0]
    print(f"  合計: {len(all_profits)}件  純損益: ¥{sum(all_profits):+.0f}")
    if p and l:
        print(f"  全体PF: {abs(sum(p)/sum(l)):.2f}  全体勝率: {len(p)/len(all_profits)*100:.1f}%")
    print()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        # サンプルデータで動作確認
        print("使い方: python3 analyze_trades.py <MT5エクスポートCSV>")
        print()
        print("MT5での書き出し手順:")
        print("  口座履歴タブ → 右クリック → 列の表示 → 「マジック」にチェック")
        print("  右クリック → レポート → CSVで保存")
    else:
        analyze(sys.argv[1])
