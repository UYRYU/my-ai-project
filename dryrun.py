"""
期間別ドライラン (手数料感度分析版)
  4レジーム × 5コスト水準 でクロス検証
  コスト = スプレッド(片道) + 往復コミッション
  XAUUSD 0.01lot:  スプレッド20pts=$0.20, コミッション$3.5/lot=$0.035/0.01lot
"""

import numpy as np
import time
from typing import List, Optional
from dataclasses import dataclass

# ── 最優秀パラメータ (optimize.py の結果) ────────────────────────
BEST_PARAMS = {
    "EMA_FAST": 12, "EMA_SLOW": 30,
    "RSI_BUY_MIN": 52.0, "RSI_SELL_MAX": 40.0,
    "ATR_MIN_POINTS": 100.0,
    "TAKE_PROFIT": 800, "STOP_LOSS": 100,
    "TRAILING_START": 80, "TRAILING_STEP": 50,
    "TRAILING_ON": True, "CLOSE_ON_SIGNAL": True,
    "MAX_CONSEC_LOSS": 3, "COOLDOWN_BARS": 30,
    "RSI_PERIOD": 14, "ATR_PERIOD": 14,
    "LOT_SIZE": 0.01, "MAX_SPREAD": 500,  # 上限を高めに (各シナリオで個別設定)
    "SPREAD_POINTS": 20, "POINT": 0.01, "LOT_VALUE": 1.0,
}

INITIAL_CAPITAL  = 1000.0
M1_BARS_PER_YEAR = 298_080
BARS_PER_PERIOD  = 99_000   # 約69日分

# ── コストシナリオ (スプレッド pts + 往復コミッション $) ────────────
# XAUUSD 0.01lot 参考値:
#   ECN口座: スプレッド15pts + コミッション$7/lot → 往復=$0.07+$0.15=$0.22
#   標準口座: スプレッド30〜50pts、コミッションなし
COST_SCENARIOS = {
    "① 超低コスト  (spread=15pts, comm=$0.00)": {"spread_pts": 15,  "commission": 0.000},
    "② ECN標準    (spread=15pts, comm=$0.07)": {"spread_pts": 15,  "commission": 0.035},
    "③ 標準口座   (spread=30pts, comm=$0.00)": {"spread_pts": 30,  "commission": 0.000},
    "④ 高コスト   (spread=50pts, comm=$0.07)": {"spread_pts": 50,  "commission": 0.035},
    "⑤ 最悪ケース (spread=80pts, comm=$0.10)": {"spread_pts": 80,  "commission": 0.050},
}

# ── 相場レジーム定義 ─────────────────────────────────────────────
PERIODS = {
    # mu は1バー当たりのドリフト。99kバーで+15%なら mu≈log(1.15)/99000≈1.4e-6
    "A: 強上昇トレンド\n   (コロナ後ラリー風)": {
        "mu": 0.0000014, "sigma": 0.0007,
        "spike_prob": 0.002, "spike_size": 0.005, "seed": 1,
    },
    "B: 高ボラ・チョッピー\n   (利上げ相場風)": {
        "mu": -0.0000005, "sigma": 0.0018,
        "spike_prob": 0.008, "spike_size": 0.015, "seed": 2,
    },
    "C: レンジ相場\n   (2023年前半風)": {
        "mu": 0.0, "sigma": 0.0005,
        "spike_prob": 0.001, "spike_size": 0.004, "seed": 3,
        "mean_revert": 0.003,
    },
    "D: 緩やか上昇\n   (2024年直近風)": {
        "mu": 0.0000008, "sigma": 0.0009,
        "spike_prob": 0.003, "spike_size": 0.007, "seed": 4,
    },
}

# ── データ生成 (レジーム対応) ────────────────────────────────────
def generate_period(cfg: dict, n: int = BARS_PER_PERIOD) -> tuple:
    rng   = np.random.default_rng(cfg["seed"])
    mu    = cfg["mu"]; sigma = cfg["sigma"]
    sp    = cfg.get("spike_prob", 0.002)
    ss    = cfg.get("spike_size", 0.010)
    mr    = cfg.get("mean_revert", 0.0)
    mean  = 2000.0

    closes = np.empty(n); closes[0] = 2000.0
    for i in range(1, n):
        spike = rng.choice([-1, 1]) * ss if rng.random() < sp else 0.0
        rev   = -mr * (closes[i-1] - mean) / mean if mr else 0.0
        ret   = rng.normal(mu + rev, sigma) + spike
        closes[i] = max(closes[i-1] * (1 + ret), 1000.0)

    noise = rng.uniform(0.03, 0.25, n)
    highs = closes * (1 + noise * sigma * 2)
    lows  = closes * (1 - noise * sigma * 2)
    return closes, highs, lows

# ── インジケーター ───────────────────────────────────────────────
def ema(arr, p):
    a = 2.0 / (p + 1); r = np.empty_like(arr); r[0] = arr[0]
    for i in range(1, len(arr)): r[i] = a*arr[i] + (1-a)*r[i-1]
    return r

def rsi_ind(arr, p):
    d = np.diff(arr, prepend=arr[0])
    g = np.where(d>0, d, 0.0); l = np.where(d<0, -d, 0.0)
    a = 1.0/p
    ag = np.empty_like(arr); ag[0] = g[0]
    al = np.empty_like(arr); al[0] = l[0]
    for i in range(1, len(arr)):
        ag[i] = a*g[i]+(1-a)*ag[i-1]; al[i] = a*l[i]+(1-a)*al[i-1]
    return 100.0 - 100.0/(1.0 + np.where(al==0, 1e-10, ag/al))

def atr_ind(hi, lo, cl, p):
    pc = np.roll(cl,1); pc[0] = cl[0]
    tr = np.maximum(hi-lo, np.maximum(np.abs(hi-pc), np.abs(lo-pc)))
    a  = 1.0/p; r = np.empty_like(tr); r[0] = tr[0]
    for i in range(1, len(tr)): r[i] = a*tr[i]+(1-a)*r[i-1]
    return r

# ── バックテストコア ─────────────────────────────────────────────
@dataclass
class Pos:
    direction: str; open_price: float; sl: float; tp: float; open_bar: int

def backtest(closes, highs, lows, p, commission: float = 0.0) -> List[float]:
    ef = ema(closes, p["EMA_FAST"]); es = ema(closes, p["EMA_SLOW"])
    rs = rsi_ind(closes, p["RSI_PERIOD"])
    at = atr_ind(highs, lows, closes, p["ATR_PERIOD"])
    PT = p["POINT"]; LV = p["LOT_VALUE"]; LS = p["LOT_SIZE"]
    SPR = p["SPREAD_POINTS"]*PT; warm = p["EMA_SLOW"]+p["RSI_PERIOD"]+5
    COMM = commission * 2  # 往復コミッション
    pos: Optional[Pos] = None; trades=[]; consec=0; cooldown=0

    for i in range(warm, len(closes)):
        bid = closes[i]; ask = bid+SPR
        if pos and p["TRAILING_ON"]:
            if pos.direction=="buy":
                if (bid-pos.open_price)/PT >= p["TRAILING_START"]:
                    nsl=bid-p["TRAILING_STEP"]*PT
                    if nsl>pos.sl: pos.sl=nsl
            else:
                if (pos.open_price-ask)/PT >= p["TRAILING_START"]:
                    nsl=ask+p["TRAILING_STEP"]*PT
                    if pos.sl==0 or nsl<pos.sl: pos.sl=nsl
        if pos:
            res=None
            if pos.direction=="buy":
                if lows[i]<=pos.sl:   res=(pos.sl-pos.open_price)/PT*LV*LS - COMM
                elif highs[i]>=pos.tp: res=(pos.tp-pos.open_price)/PT*LV*LS - COMM
            else:
                if highs[i]>=pos.sl:  res=(pos.open_price-pos.sl)/PT*LV*LS - COMM
                elif lows[i]<=pos.tp:  res=(pos.open_price-pos.tp)/PT*LV*LS - COMM
            if res is not None:
                trades.append(res); consec=consec+1 if res<0 else 0
                if consec>=p["MAX_CONSEC_LOSS"]: cooldown=i+p["COOLDOWN_BARS"]; consec=0
                pos=None; continue
        if i<=cooldown: continue
        j=i-1
        if at[j]/PT < p["ATR_MIN_POINTS"]: continue
        buy  = (ef[j]>es[j]) and (rs[j]>=p["RSI_BUY_MIN"])
        sell = (ef[j]<es[j]) and (rs[j]<=p["RSI_SELL_MAX"])
        if pos:
            if p["CLOSE_ON_SIGNAL"]:
                if pos.direction=="buy" and sell:
                    r=(bid-pos.open_price)/PT*LV*LS - COMM; trades.append(r)
                    consec=consec+1 if r<0 else 0
                    if consec>=p["MAX_CONSEC_LOSS"]: cooldown=i+p["COOLDOWN_BARS"]; consec=0
                    pos=None
                elif pos.direction=="sell" and buy:
                    r=(pos.open_price-ask)/PT*LV*LS - COMM; trades.append(r)
                    consec=consec+1 if r<0 else 0
                    if consec>=p["MAX_CONSEC_LOSS"]: cooldown=i+p["COOLDOWN_BARS"]; consec=0
                    pos=None
        else:
            if buy:  pos=Pos("buy",  ask, ask-p["STOP_LOSS"]*PT, ask+p["TAKE_PROFIT"]*PT, i)
            elif sell: pos=Pos("sell",bid, bid+p["STOP_LOSS"]*PT, bid-p["TAKE_PROFIT"]*PT, i)
    return trades

# ── 統計 ─────────────────────────────────────────────────────────
def stats(trades, n_bars):
    if len(trades) < 10:
        return None
    t   = np.array(trades); eq = np.cumsum(t)
    net = float(eq[-1])
    dd  = float(np.min(eq - np.maximum.accumulate(eq)))
    nw  = int((t>0).sum()); nl = int((t<=0).sum())
    pf  = abs(float(t[t>0].sum())/float(t[t<=0].sum())) if nl else 999
    ann = (net/INITIAL_CAPITAL)*(M1_BARS_PER_YEAR/n_bars)*100
    mdd = abs(dd)/INITIAL_CAPITAL*100
    cal = ann/mdd if mdd>0 else 0
    return {"net":net,"dd":dd,"pf":pf,"wr":nw/len(t)*100,
            "n":len(t),"ann":ann,"mdd":mdd,"cal":cal}

# ── レポート ─────────────────────────────────────────────────────
def cell(ann):
    if ann is None:   return "    ──   "
    if ann >=  100:   return f"\033[32m{ann:>+7.0f}%\033[0m"   # 緑
    if ann >=    0:   return f"\033[33m{ann:>+7.0f}%\033[0m"   # 黄
    return                   f"\033[31m{ann:>+7.0f}%\033[0m"   # 赤

def print_cross_table(matrix: dict, period_names: list, cost_names: list):
    W = 74
    print()
    print("=" * W)
    print("  手数料感度分析 — 年利(推定)クロス表")
    print(f"  初期資金 $1,000 / 0.01ロット / ※合成データ推計値")
    print("=" * W)

    # ヘッダー
    hdr = f"  {'コストシナリオ':<32}"
    for pn in period_names:
        hdr += f" {pn.split(':')[0]:>9}"
    hdr += f"  {'平均':>8}  損益分岐"
    print(hdr)
    print("─" * W)

    breakeven_costs = []
    for cn in cost_names:
        row_anns = []
        for pn in period_names:
            st = matrix.get((cn, pn))
            row_anns.append(st["ann"] if st else None)

        valid = [v for v in row_anns if v is not None]
        avg   = np.mean(valid) if valid else None
        pos_c = sum(1 for v in valid if v > 0)

        label = cn[:30]
        line  = f"  {label:<32}"
        for ann in row_anns:
            line += f" {cell(ann):>9}"
        avg_str = f"{avg:>+7.0f}%" if avg is not None else "   ──  "
        be_str  = f"{pos_c}/{len(valid)}黒字"
        print(line + f"  \033[0m{avg_str}  {be_str}")
        breakeven_costs.append((cn, avg, pos_c, len(valid)))

    print("─" * W)
    # PF行
    pf_row = f"  {'[参考] PF':<32}"
    for pn in period_names:
        st = matrix.get((cost_names[0], pn))
        pf_row += f" {st['pf']:>8.2f} " if st else f" {'──':>9}"
    print(pf_row)
    print("=" * W)

    # 損益分岐ライン
    print()
    print("  ── 損益分岐コスト分析 ──────────────────────────────────")
    for cn, avg, pos_c, total in breakeven_costs:
        label = cn[:35]
        ok = "✓ 全期間黒字" if pos_c == total else (f"△ {pos_c}/{total}黒字" if pos_c >= total*0.75 else f"✗ {pos_c}/{total}黒字")
        avg_s = f"平均年利{avg:+.0f}%" if avg else ""
        print(f"  {label}  {avg_s}  {ok}")

    print()
    print("  ※ 年利は合成データ推計値。MT5実ティックデータでの検証が必須。")
    print("=" * W)


# ── メイン ───────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 74)
    print("  手数料感度分析ドライラン")
    print(f"  各期間: {BARS_PER_PERIOD:,} バー (M1換算 約{BARS_PER_PERIOD//60//24}日分)")
    print(f"  コストシナリオ: {len(COST_SCENARIOS)}種  ×  相場レジーム: {len(PERIODS)}種")
    print("=" * 74)

    # 先にOHLCデータを全期間生成
    period_data = {}
    for pname, cfg in PERIODS.items():
        period_data[pname] = generate_period(cfg, BARS_PER_PERIOD)

    matrix = {}
    total_runs = len(COST_SCENARIOS) * len(PERIODS)
    run = 0
    t0  = time.time()

    for cname, ccfg in COST_SCENARIOS.items():
        p = dict(BEST_PARAMS)
        p["SPREAD_POINTS"] = ccfg["spread_pts"]
        p["MAX_SPREAD"]    = ccfg["spread_pts"] + 10
        comm = ccfg["commission"]

        for pname, (closes, highs, lows) in period_data.items():
            trades = backtest(closes, highs, lows, p, commission=comm)
            st     = stats(trades, BARS_PER_PERIOD)
            matrix[(cname, pname)] = st
            run += 1

    print(f"  完了 {time.time()-t0:.1f}s ({total_runs}ケース)\n")

    period_names = list(PERIODS.keys())
    cost_names   = list(COST_SCENARIOS.keys())
    print_cross_table(matrix, period_names, cost_names)
