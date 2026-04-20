"""
XAU_Scalper_EMA_RSI パラメータ最適化 (年利特化版)
  - ランダムサーチ 500 試行
  - ウォークフォワード検証 (70% IS / 30% OOS)
  - スコア = カルマーレシオ (年利 / |最大DD|)
  - 初期資金 $1000 / 0.01ロット 想定
"""

import numpy as np
import random
import time
from dataclasses import dataclass
from typing import Optional, List, Tuple

# ============================================================
# 設定
# ============================================================
INITIAL_CAPITAL  = 1000.0   # 想定初期資金 ($)
M1_BARS_PER_YEAR = 298_080  # M1バー/年 (23h×60×252営業日 ≒ 298k)

SEARCH_SPACE = {
    "EMA_FAST":       [5, 7, 9, 12, 15],
    "EMA_SLOW":       [18, 21, 25, 30, 35],
    "RSI_BUY_MIN":    [45, 50, 52, 55, 58, 60],
    "RSI_SELL_MAX":   [40, 42, 45, 48, 50, 55],
    "ATR_MIN_POINTS": [50, 80, 100, 130, 160, 200],
    "TAKE_PROFIT":    [300, 400, 500, 600, 800, 1000],
    "STOP_LOSS":      [100, 150, 200, 250, 300],
    "TRAILING_START": [80, 100, 150, 200, 250],
    "TRAILING_STEP":  [40, 50, 70, 100, 130],
}

FIXED = {
    "LOT_SIZE":        0.01,
    "MAX_SPREAD":      50,
    "RSI_PERIOD":      14,
    "ATR_PERIOD":      14,
    "TRAILING_ON":     True,
    "CLOSE_ON_SIGNAL": True,
    "MAX_CONSEC_LOSS": 3,
    "COOLDOWN_BARS":   30,
    "SPREAD_POINTS":   20,
    "POINT":           0.01,
    "LOT_VALUE":       1.0,
}

N_TRIALS   = 500
N_BARS     = 26000   # 約18日分
IS_RATIO   = 0.70
MIN_TRADES = 40
TOP_K      = 10

# ============================================================
# データ生成
# ============================================================
def generate_ohlcv(n: int, seed: int = 42) -> tuple:
    rng = np.random.default_rng(seed)
    mu, sigma = 0.00005, 0.0008
    closes    = np.empty(n)
    closes[0] = 2000.0
    for i in range(1, n):
        closes[i] = closes[i-1] * (1 + rng.normal(mu, sigma))
    noise = rng.uniform(0.05, 0.20, n)
    highs = closes * (1 + noise * 0.0005)
    lows  = closes * (1 - noise * 0.0005)
    return closes, highs, lows

# ============================================================
# インジケーター (numpy高速版)
# ============================================================
def ema(arr, period):
    a = 2.0 / (period + 1)
    r = np.empty_like(arr); r[0] = arr[0]
    for i in range(1, len(arr)):
        r[i] = a * arr[i] + (1 - a) * r[i-1]
    return r

def rsi(arr, period):
    d  = np.diff(arr, prepend=arr[0])
    g  = np.where(d > 0, d, 0.0)
    l  = np.where(d < 0, -d, 0.0)
    a  = 1.0 / period
    ag = np.empty_like(arr); ag[0] = g[0]
    al = np.empty_like(arr); al[0] = l[0]
    for i in range(1, len(arr)):
        ag[i] = a * g[i] + (1 - a) * ag[i-1]
        al[i] = a * l[i] + (1 - a) * al[i-1]
    return 100.0 - 100.0 / (1.0 + np.where(al == 0, 1e-10, ag / al))

def atr(high, low, close, period):
    pc = np.roll(close, 1); pc[0] = close[0]
    tr = np.maximum(high - low, np.maximum(np.abs(high - pc), np.abs(low - pc)))
    a  = 1.0 / period
    r  = np.empty_like(tr); r[0] = tr[0]
    for i in range(1, len(tr)):
        r[i] = a * tr[i] + (1 - a) * r[i-1]
    return r

# ============================================================
# バックテストコア
# ============================================================
@dataclass
class Pos:
    direction: str
    open_price: float
    sl: float
    tp: float
    open_bar: int

def backtest(closes, highs, lows, p) -> List[float]:
    ef   = ema(closes, p["EMA_FAST"])
    es   = ema(closes, p["EMA_SLOW"])
    rs   = rsi(closes, p["RSI_PERIOD"])
    at   = atr(highs, lows, closes, p["ATR_PERIOD"])

    PT   = p["POINT"]; LV = p["LOT_VALUE"]; LS = p["LOT_SIZE"]
    SPR  = p["SPREAD_POINTS"] * PT
    warm = p["EMA_SLOW"] + p["RSI_PERIOD"] + 5

    pos: Optional[Pos] = None
    trades: List[float] = []
    consec = 0; cooldown = 0

    for i in range(warm, len(closes)):
        bid = closes[i]; ask = bid + SPR

        # トレーリング
        if pos and p["TRAILING_ON"]:
            if pos.direction == "buy":
                if (bid - pos.open_price) / PT >= p["TRAILING_START"]:
                    nsl = bid - p["TRAILING_STEP"] * PT
                    if nsl > pos.sl: pos.sl = nsl
            else:
                if (pos.open_price - ask) / PT >= p["TRAILING_START"]:
                    nsl = ask + p["TRAILING_STEP"] * PT
                    if pos.sl == 0 or nsl < pos.sl: pos.sl = nsl

        # TP / SL
        if pos:
            result = None
            if pos.direction == "buy":
                if lows[i] <= pos.sl:  result = (pos.sl - pos.open_price) / PT * LV * LS
                elif highs[i] >= pos.tp: result = (pos.tp - pos.open_price) / PT * LV * LS
            else:
                if highs[i] >= pos.sl: result = (pos.open_price - pos.sl) / PT * LV * LS
                elif lows[i] <= pos.tp: result = (pos.open_price - pos.tp) / PT * LV * LS

            if result is not None:
                trades.append(result)
                consec = consec + 1 if result < 0 else 0
                if consec >= p["MAX_CONSEC_LOSS"]: cooldown = i + p["COOLDOWN_BARS"]; consec = 0
                pos = None; continue

        if i <= cooldown: continue
        j = i - 1
        if at[j] / PT < p["ATR_MIN_POINTS"]: continue

        buy  = (ef[j] > es[j]) and (rs[j] >= p["RSI_BUY_MIN"])
        sell = (ef[j] < es[j]) and (rs[j] <= p["RSI_SELL_MAX"])

        if pos:
            if p["CLOSE_ON_SIGNAL"]:
                if pos.direction == "buy" and sell:
                    r = (bid - pos.open_price) / PT * LV * LS
                    trades.append(r)
                    consec = consec + 1 if r < 0 else 0
                    if consec >= p["MAX_CONSEC_LOSS"]: cooldown = i + p["COOLDOWN_BARS"]; consec = 0
                    pos = None
                elif pos.direction == "sell" and buy:
                    r = (pos.open_price - ask) / PT * LV * LS
                    trades.append(r)
                    consec = consec + 1 if r < 0 else 0
                    if consec >= p["MAX_CONSEC_LOSS"]: cooldown = i + p["COOLDOWN_BARS"]; consec = 0
                    pos = None
        else:
            if buy:  pos = Pos("buy",  ask, ask - p["STOP_LOSS"]*PT, ask + p["TAKE_PROFIT"]*PT, i)
            elif sell: pos = Pos("sell", bid, bid + p["STOP_LOSS"]*PT, bid - p["TAKE_PROFIT"]*PT, i)

    return trades

# ============================================================
# 統計計算 (年利付き)
# ============================================================
def calc_stats(trades: List[float], n_bars: int) -> dict:
    if len(trades) < MIN_TRADES:
        return {}
    t   = np.array(trades)
    eq  = np.cumsum(t)
    net = float(eq[-1])
    dd  = float(np.min(eq - np.maximum.accumulate(eq)))
    if dd == 0: return {}

    nw  = int((t > 0).sum())
    pf  = abs(float(t[t>0].sum()) / float(t[t<=0].sum())) if (t<=0).any() else 999

    # 年利 = (純損益 / 初期資金) × (年間バー数 / テストバー数)
    annual_return = (net / INITIAL_CAPITAL) * (M1_BARS_PER_YEAR / n_bars) * 100

    # カルマーレシオ = 年利 / |最大DD率|
    max_dd_pct    = abs(dd) / INITIAL_CAPITAL * 100
    calmar        = annual_return / max_dd_pct if max_dd_pct > 0 else 0

    return {
        "net": net, "dd": dd, "pf": pf,
        "wr": nw / len(t) * 100, "n": len(t),
        "annual_pct": annual_return,
        "max_dd_pct": max_dd_pct,
        "calmar": calmar,
    }

# ============================================================
# ランダムサーチ
# ============================================================
def random_params(seed=None) -> dict:
    rng = random.Random(seed)
    p   = {k: rng.choice(v) for k, v in SEARCH_SPACE.items()}
    p.update(FIXED)
    if p["EMA_FAST"] >= p["EMA_SLOW"]:
        p["EMA_SLOW"] = p["EMA_FAST"] + rng.choice([9, 12, 15, 18])
    return p

def run_optimization(closes, highs, lows):
    n     = len(closes)
    sp    = int(n * IS_RATIO)
    ic, ih, il = closes[:sp], highs[:sp], lows[:sp]
    oc, oh, ol = closes[sp:], highs[sp:], lows[sp:]

    results = []
    t0 = time.time()
    print(f"ランダムサーチ {N_TRIALS} 試行 (目標: 年利最大化)...")

    for trial in range(N_TRIALS):
        p   = random_params(trial)
        tr  = backtest(ic, ih, il, p)
        st  = calc_stats(tr, sp)
        if st:
            results.append({"params": p, "is": st, "trial": trial})
        if (trial + 1) % 100 == 0:
            elapsed = time.time() - t0
            print(f"  [{trial+1:>4}/{N_TRIALS}]  有効={len(results)}件  {elapsed:.0f}s経過")

    print(f"\n完了 ({time.time()-t0:.1f}s) | 有効: {len(results)}/{N_TRIALS}\n")

    # カルマーレシオでソート
    results.sort(key=lambda x: x["is"]["calmar"], reverse=True)
    top = results[:TOP_K]

    print("OOS検証中...")
    for r in top:
        tr = backtest(oc, oh, ol, r["params"])
        st = calc_stats(tr, n - sp)
        r["oos"] = st if st else {"net":0,"dd":0,"pf":0,"wr":0,"n":0,"annual_pct":0,"max_dd_pct":0,"calmar":0}

    return top

# ============================================================
# レポート
# ============================================================
def print_report(top):
    print("=" * 78)
    print("  最適化結果 TOP", TOP_K, f"  (初期資金 ${INITIAL_CAPITAL:.0f} / 0.01lot)")
    print(f"  {'#':<3} {'Calmar':>7} {'IS年利':>8} {'IS DD%':>7} {'IS PF':>6} {'IS 勝率':>7} |"
          f" {'OOS年利':>8} {'OOS DD%':>7} {'OOS PF':>6}")
    print("-" * 78)
    for i, r in enumerate(top, 1):
        IS  = r["is"]; OOS = r["oos"]
        print(f"  {i:<3} {IS['calmar']:>7.2f} {IS['annual_pct']:>7.1f}%"
              f" {IS['max_dd_pct']:>6.1f}% {IS['pf']:>6.2f} {IS['wr']:>6.1f}%"
              f" | {OOS['annual_pct']:>7.1f}% {OOS['max_dd_pct']:>6.1f}% {OOS['pf']:>6.2f}")
    print("=" * 78)

    best = top[0]
    p    = best["params"]
    IS   = best["is"]
    OOS  = best["oos"]

    print(f"""
  ★ 最優秀パラメータ  (カルマーレシオ最高)
{"─"*78}
  EMA Fast / Slow       : {p['EMA_FAST']} / {p['EMA_SLOW']}
  RSI 買下限 / 売上限   : {p['RSI_BUY_MIN']} / {p['RSI_SELL_MAX']}
  ATR 最小閾値          : {p['ATR_MIN_POINTS']} points
  TP / SL               : {p['TAKE_PROFIT']} / {p['STOP_LOSS']} points
  Trailing Start / Step : {p['TRAILING_START']} / {p['TRAILING_STEP']} points

  ┌─────────────────────────────────────────┐
  │           パフォーマンス概要             │
  │  区分    年利(推定)  最大DD   PF   勝率  │
  │  IS70%   {IS['annual_pct']:>+7.1f}%  {IS['max_dd_pct']:>5.1f}%  {IS['pf']:>4.2f}  {IS['wr']:>4.1f}% │
  │  OOS30%  {OOS['annual_pct']:>+7.1f}%  {OOS['max_dd_pct']:>5.1f}%  {OOS['pf']:>4.2f}  {OOS['wr']:>4.1f}% │
  └─────────────────────────────────────────┘""")

    # OOS評価
    oos_yr = OOS["annual_pct"]
    print(f"\n  OOS年利 {oos_yr:+.1f}%  →  ", end="")
    if   oos_yr >= 50:  print("★★★ 非常に良好")
    elif oos_yr >= 20:  print("★★  良好")
    elif oos_yr >= 0:   print("★   プラス圏")
    else:               print("✗   マイナス — パラメータ再検討を")

    is_yr = IS["annual_pct"]
    if is_yr > 0:
        decay = (oos_yr - is_yr) / abs(is_yr) * 100
        print(f"  IS→OOS劣化: {decay:+.0f}%  ", end="")
        print("(過学習リスク低)" if decay > -40 else "(過学習注意)")

    print(f"""
  ── EAへの反映値 ────────────────────────────────────────────────────
  InpEmaFast       = {p['EMA_FAST']}
  InpEmaSlow       = {p['EMA_SLOW']}
  InpRsiBuyMin     = {p['RSI_BUY_MIN']}.0
  InpRsiSellMax    = {p['RSI_SELL_MAX']}.0
  InpAtrMinPoints  = {p['ATR_MIN_POINTS']}.0
  InpTakeProfit    = {p['TAKE_PROFIT']}
  InpStopLoss      = {p['STOP_LOSS']}
  InpTrailingStart = {p['TRAILING_START']}
  InpTrailingStep  = {p['TRAILING_STEP']}
{"="*78}
  ※ 年利は合成データ推計値。MT5実ティックデータでの検証が必須。
{"="*78}""")

# ============================================================
# メイン
# ============================================================
if __name__ == "__main__":
    print(f"データ生成: {N_BARS}バー / 初期資金: ${INITIAL_CAPITAL}")
    closes, highs, lows = generate_ohlcv(N_BARS)
    top = run_optimization(closes, highs, lows)
    print_report(top)
