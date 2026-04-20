"""
期間別ドライラン (Multi-Period Dry Run)
  4つの相場レジーム × 各3ヶ月分 (M1相当) をシミュレート
  - Period A: 強い上昇トレンド  (2020年コロナ後ラリー風)
  - Period B: 高ボラ・チョッピー (2022年利上げ相場風)
  - Period C: レンジ相場        (2023年前半風)
  - Period D: 緩やかな上昇      (2024年直近風)
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
    "LOT_SIZE": 0.01, "MAX_SPREAD": 50,
    "SPREAD_POINTS": 20, "POINT": 0.01, "LOT_VALUE": 1.0,
}

INITIAL_CAPITAL  = 1000.0
M1_BARS_PER_YEAR = 298_080
BARS_PER_PERIOD  = 99_000   # 約69日 × 3 ≒ 約3ヶ月分

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

def backtest(closes, highs, lows, p) -> List[float]:
    ef = ema(closes, p["EMA_FAST"]); es = ema(closes, p["EMA_SLOW"])
    rs = rsi_ind(closes, p["RSI_PERIOD"])
    at = atr_ind(highs, lows, closes, p["ATR_PERIOD"])
    PT = p["POINT"]; LV = p["LOT_VALUE"]; LS = p["LOT_SIZE"]
    SPR = p["SPREAD_POINTS"]*PT; warm = p["EMA_SLOW"]+p["RSI_PERIOD"]+5
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
                if lows[i]<=pos.sl:   res=(pos.sl-pos.open_price)/PT*LV*LS
                elif highs[i]>=pos.tp: res=(pos.tp-pos.open_price)/PT*LV*LS
            else:
                if highs[i]>=pos.sl:  res=(pos.open_price-pos.sl)/PT*LV*LS
                elif lows[i]<=pos.tp:  res=(pos.open_price-pos.tp)/PT*LV*LS
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
                    r=(bid-pos.open_price)/PT*LV*LS; trades.append(r)
                    consec=consec+1 if r<0 else 0
                    if consec>=p["MAX_CONSEC_LOSS"]: cooldown=i+p["COOLDOWN_BARS"]; consec=0
                    pos=None
                elif pos.direction=="sell" and buy:
                    r=(pos.open_price-ask)/PT*LV*LS; trades.append(r)
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
def verdict(ann):
    if ann >= 100: return "★★★ 優秀"
    if ann >= 30:  return "★★  良好"
    if ann >= 0:   return "★   プラス"
    return              "✗   マイナス"

def print_report(results: dict):
    print()
    print("╔" + "═"*70 + "╗")
    print("║  期間別ドライラン結果  (パラメータ: optimize.py 最優秀値)" + " "*13 + "║")
    print("║  初期資金 $1,000 / 0.01ロット / スプレッド20pts固定" + " "*18 + "║")
    print("╠" + "═"*70 + "╣")
    print(f"║  {'期間':<28} {'年利(推定)':>10} {'最大DD':>7} {'PF':>5} {'勝率':>6} {'N':>5} {'評価':>10} ║")
    print("╠" + "═"*70 + "╣")

    total_net = 0
    all_trades = []
    for name, st in results.items():
        label = name.split('\n')[0]  # 1行目だけ使う
        if st:
            total_net += st["net"]
            bar = "▓" * min(int(abs(st["ann"]) / 50), 12)
            sign = "+" if st["ann"] >= 0 else ""
            v = verdict(st["ann"])
            print(f"║  {label:<26} {sign}{st['ann']:>8.1f}% {st['mdd']:>6.1f}% {st['pf']:>5.2f} {st['wr']:>5.1f}% {st['n']:>5}  {v:<10} ║")
        else:
            print(f"║  {label:<26} {'データ不足':>10}" + " "*35 + "║")

    print("╠" + "═"*70 + "╣")

    # 全期間合算
    all_t = []
    for nm, st in results.items():
        all_t  # placeholder
    ann_vals = [st["ann"] for st in results.values() if st]
    pf_vals  = [st["pf"]  for st in results.values() if st]
    avg_ann  = np.mean(ann_vals) if ann_vals else 0
    avg_pf   = np.mean(pf_vals)  if pf_vals else 0
    win_pds  = sum(1 for v in ann_vals if v > 0)

    print(f"║  {'全期間平均':<26} {avg_ann:>+9.1f}% {'─':>7} {avg_pf:>5.2f} {'─':>6} {'─':>5}  {win_pds}/{len(ann_vals)}期間黒字  ║")
    print("╚" + "═"*70 + "╝")

    # 詳細
    print()
    for name, st in results.items():
        if not st: continue
        label = name.replace('\n   ', ' ')
        print(f"  【{label}】")
        print(f"    純損益: ${st['net']:+.2f}  年利: {st['ann']:+.1f}%  最大DD: {st['mdd']:.1f}%  カルマー: {st['cal']:.1f}")
        print(f"    トレード: {st['n']}件  勝率: {st['wr']:.1f}%  PF: {st['pf']:.2f}")
        print()

    # 総括
    print("─"*72)
    if win_pds == len(ann_vals):
        print("  ✓ 全期間でプラス — 相場環境への頑健性あり")
    elif win_pds >= len(ann_vals) * 0.75:
        print("  △ 大半の期間でプラス — 特定レジームに弱点あり")
    else:
        print("  ✗ マイナス期間が多い — パラメータ再検討推奨")
    print(f"  平均年利 {avg_ann:+.1f}%  ※合成データ推計値。実データ検証が必須。")
    print("─"*72)

# ── メイン ───────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 72)
    print("  期間別ドライラン開始")
    print(f"  各期間: {BARS_PER_PERIOD:,} バー (M1換算 約{BARS_PER_PERIOD//60//24}日分)")
    print("=" * 72)

    results = {}
    for name, cfg in PERIODS.items():
        label = name.split('\n')[0]
        print(f"  [{label}] データ生成・バックテスト中...", end=" ", flush=True)
        t0 = time.time()
        closes, highs, lows = generate_period(cfg, BARS_PER_PERIOD)
        trades = backtest(closes, highs, lows, BEST_PARAMS)
        st = stats(trades, BARS_PER_PERIOD)
        results[name] = st
        print(f"{time.time()-t0:.1f}s  → {len(trades)}件", flush=True)

    print_report(results)
