"""
両建てEA バックテスト
================
ロジック:
  - 1分ごとに BUY と SELL を 1 ポジションずつ同時エントリー（バーの始値）
  - BUY群 / SELL群 で別々に管理
  - 各群の含み益が閾値(保有数Nに依存)を超えたら、その群を全決済
  - これを延々繰り返す

価格データ:
  - 実データ取得が当環境で不可だったため、リアルなFX（USDJPY想定）の
    1分足を幾何ブラウン運動で合成。複数シードで平均化して頑健性を確認。

サイズ/コスト:
  - 1ポジ = 1,000通貨 (0.01ロット相当)
  - 価格1円(=100pips)動くと 1ポジあたり 1,000円 損益
  - つまり 0.05円(=5pips) 動けば 50円利益 ⇒ ユーザー要件と整合
  - スプレッド: 0.2pip = 0.002円 (片道コスト 2円/ポジ) を考慮
"""

import math
import random
import statistics

# ---------------- 価格生成 ----------------
def generate_prices(n_bars, seed, start=150.0, sigma_per_min=0.015):
    random.seed(seed)
    prices = [start]
    for _ in range(n_bars - 1):
        # 微小ドリフト無し、正規ノイズ
        prices.append(prices[-1] + random.gauss(0, sigma_per_min))
    return prices

# ---------------- バックテスト本体 ----------------
UNITS = 1000              # 1ポジあたりの通貨数
SPREAD = 0.002            # 0.2pip (円)
COST_PER_POS = SPREAD * UNITS  # = 2円

def run_backtest(prices, target_fn, initial_balance=10000):
    """
    target_fn(n) -> n ポジ保有時の決済利益閾値(円)
    """
    balance = initial_balance
    equity_curve = [balance]

    buy_entries = []   # 各エントリーの価格
    sell_entries = []

    closes_buy = 0
    closes_sell = 0
    max_dd = 0
    peak = balance

    for p in prices:
        # 1) エントリー (両建て)
        buy_entries.append(p)
        sell_entries.append(p)

        # 2) 決済判定 — BUY群
        if buy_entries:
            n = len(buy_entries)
            floating = sum((p - e) for e in buy_entries) * UNITS - COST_PER_POS * n
            if floating >= target_fn(n):
                balance += floating
                buy_entries = []
                closes_buy += 1

        # 3) 決済判定 — SELL群
        if sell_entries:
            n = len(sell_entries)
            floating = sum((e - p) for e in sell_entries) * UNITS - COST_PER_POS * n
            if floating >= target_fn(n):
                balance += floating
                sell_entries = []
                closes_sell += 1

        # 4) エクイティ(含み損益込み)
        eq = balance
        if buy_entries:
            eq += sum((p - e) for e in buy_entries) * UNITS - COST_PER_POS * len(buy_entries)
        if sell_entries:
            eq += sum((e - p) for e in sell_entries) * UNITS - COST_PER_POS * len(sell_entries)
        equity_curve.append(eq)

        peak = max(peak, eq)
        dd = peak - eq
        if dd > max_dd:
            max_dd = dd

        # 強制ロスカット (口座が0以下)
        if eq <= 0:
            return {
                "final_balance": balance,
                "final_equity": eq,
                "max_dd": max_dd,
                "closes_buy": closes_buy,
                "closes_sell": closes_sell,
                "max_buy_pos": max(len(buy_entries), 0),
                "max_sell_pos": max(len(sell_entries), 0),
                "blew_up": True,
                "bars_survived": len(equity_curve),
            }

    return {
        "final_balance": balance,
        "final_equity": equity_curve[-1],
        "max_dd": max_dd,
        "closes_buy": closes_buy,
        "closes_sell": closes_sell,
        "open_buy": len(buy_entries),
        "open_sell": len(sell_entries),
        "blew_up": False,
        "bars_survived": len(equity_curve),
    }

# ---------------- 出口戦略 ----------------
strategies = {
    "A: 比例 50*N (均等)":           lambda n: 50 * n,
    "B: 50,95,140,... (+45)":        lambda n: 50 + 45 * (n - 1) if n >= 1 else 0,
    "C: 50,90,120,140,150 で頭打ち": lambda n: [0,50,90,120,140,150,150,150,150,150][min(n,9)],
    "D: 固定 50 (Nに依らず)":         lambda n: 50,
    "E: 100*N (大きめ)":             lambda n: 100 * n,
    "F: 30*N (小さめ)":              lambda n: 30 * n,
    "G: log型 50*log2(N+1)":         lambda n: 50 * math.log2(n + 1),
    "H: 固定 100 (Nに依らず)":        lambda n: 100,
    "I: 固定 200 (Nに依らず)":        lambda n: 200,
    "J: 固定 30 (Nに依らず)":         lambda n: 30,
}

# ---------------- 実行 ----------------
SEEDS = [1, 2, 3, 4, 5, 6, 7, 8]

def sweep(label, n_bars, sigma, balance):
    """指定の足/口座サイズで全戦略を回す"""
    print(f"\n========== {label}  バー={n_bars}  σ={sigma}  口座={balance:,} ==========")
    print(f"{'戦略':<32}{'平均終値':>12}{'破綻率':>10}{'平均DD':>12}{'生残バー':>12}")
    print("-" * 80)
    for name, fn in strategies.items():
        finals, dds, blow, surv = [], [], 0, []
        for s in SEEDS:
            prices = generate_prices(n_bars, s, sigma_per_min=sigma)
            r = run_backtest(prices, fn, initial_balance=balance)
            finals.append(r["final_equity"])
            dds.append(r["max_dd"])
            surv.append(r["bars_survived"])
            if r["blew_up"]:
                blow += 1
        print(f"{name:<32}{statistics.mean(finals):>12,.0f}"
              f"{blow/len(SEEDS):>9.0%}{statistics.mean(dds):>12,.0f}"
              f"{statistics.mean(surv):>12,.0f}")

def main():
    # 1) 証拠金スイープ (M1, 20日)
    print("\n##### (1) 証拠金スイープ — M1, 20日間 #####")
    for bal in [10_000, 100_000, 1_000_000, 10_000_000]:
        sweep(f"M1 balance={bal:,}", 1440 * 20, 0.015, bal)

    # 2) タイムフレーム比較 (口座 100万円)
    # σ は √Δt でスケール: M1=0.015, M5=0.015*√5, M15=*√15, H1=*√60
    print("\n\n##### (2) タイムフレーム比較 — 口座 1,000,000 円, 20日間 #####")
    tf_specs = [
        ("M1",  1440 * 20, 0.015),
        ("M5",   288 * 20, 0.015 * math.sqrt(5)),
        ("M15",   96 * 20, 0.015 * math.sqrt(15)),
        ("H1",    24 * 20, 0.015 * math.sqrt(60)),
    ]
    for label, bars, sig in tf_specs:
        sweep(label, bars, sig, 1_000_000)

if __name__ == "__main__":
    main()
