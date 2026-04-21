"""
MT5 取引履歴 Magic Number別分析 (Excel/CSV対応)
使い方: python3 analyze_trades.py <ファイルパス>
"""

import sys
import pandas as pd
import numpy as np

MAGIC_LABELS = {
    "20240101": "①トレールあり (Magic:20240101)",
    "2024":     "②トレールなし (Magic:2024)",
}

def load_file(filepath):
    ext = filepath.lower().split(".")[-1]
    if ext in ["xlsx", "xls"]:
        # MT5レポートは上部にメタデータ行がある → headerを探す
        raw = pd.read_excel(filepath, header=None)
        # 「タイプ」または「type」がある行をヘッダーとして使う
        header_row = None
        for i, row in raw.iterrows():
            vals = [str(v).strip().lower() for v in row.values]
            if any(v in ["タイプ", "type", "sell", "buy"] for v in vals):
                if any(v in ["タイプ", "type"] for v in vals):
                    header_row = i
                    break
        if header_row is None:
            header_row = 7  # fallback
        df = pd.read_excel(filepath, header=header_row)
    else:
        for enc in ["utf-8-sig", "utf-8", "shift_jis", "cp932"]:
            try:
                df = pd.read_csv(filepath, encoding=enc, skiprows=7)
                break
            except:
                continue
    df.columns = [str(c).strip() for c in df.columns]
    return df

def find_col(df, candidates):
    for col in df.columns:
        for c in candidates:
            if c.lower() in col.lower():
                return col
    return None

def analyze(filepath):
    print(f"ファイル読み込み中: {filepath}")
    df = load_file(filepath)

    col_magic  = find_col(df, ["magic", "マジック"])
    col_profit = find_col(df, ["損益", "profit"])
    col_type   = find_col(df, ["タイプ", "type"])

    print(f"列検出 → magic:{col_magic}  profit:{col_profit}  type:{col_type}")
    print(f"総行数: {len(df)}")

    if not col_profit:
        print("\n損益列が見つかりません。列一覧:", list(df.columns))
        return

    # 取引行だけ抽出 (buy/sell)
    if col_type:
        mask = df[col_type].astype(str).str.strip().str.lower().isin(["buy","sell","買い","売り","0","1"])
        df = df[mask].copy()

    df[col_profit] = pd.to_numeric(df[col_profit].astype(str).str.replace(",","").str.replace(" ",""), errors="coerce")
    df = df.dropna(subset=[col_profit])

    if col_magic:
        df[col_magic] = df[col_magic].astype(str).str.strip().str.rstrip(".0")
        groups = df.groupby(col_magic)
    else:
        df["_all"] = "全体"
        groups = df.groupby("_all")

    print()
    print("=" * 68)
    print("  Magic Number 別 パフォーマンス比較")
    print("=" * 68)
    fmt = "  {:<30} {:>5} {:>4} {:>4} {:>7} {:>10} {:>6} {:>8} {:>8}"
    print(fmt.format("EA", "件数", "勝", "負", "勝率", "純損益", "PF", "avg勝", "avg負"))
    print("-" * 68)

    summary = []
    for magic, grp in groups:
        profits = grp[col_profit].values
        p = profits[profits > 0]
        l = profits[profits <= 0]
        n = len(profits)
        nw, nl = len(p), len(l)
        wr  = nw / n * 100 if n else 0
        net = profits.sum()
        pf  = abs(p.sum() / l.sum()) if nl and l.sum() != 0 else float("inf")
        ag  = p.mean() if nw else 0
        al  = l.mean() if nl else 0
        label = MAGIC_LABELS.get(str(magic), f"Magic:{magic}")
        print(fmt.format(label[:30], n, nw, nl, f"{wr:.1f}%", f"¥{net:+.0f}", f"{pf:.2f}", f"¥{ag:+.0f}", f"¥{al:+.0f}"))
        summary.append((magic, label, n, nw, nl, wr, net, pf, ag, al))

    print("=" * 68)

    # 判定
    if len(summary) == 2:
        a, b = summary[0], summary[1]
        print()
        print("  ── 比較結果 ─────────────────────────────────────────")
        winner_net = a[1] if a[6] > b[6] else b[1]
        winner_wr  = a[1] if a[3] > b[3] else b[1]
        winner_pf  = a[1] if a[7] > b[7] else b[1]
        print(f"  純損益  勝者: {winner_net}")
        print(f"  勝率    勝者: {winner_wr}")
        print(f"  PF      勝者: {winner_pf}")

    print()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使い方: python3 analyze_trades.py <MT5レポートファイル.xlsx or .csv>")
    else:
        analyze(sys.argv[1])
