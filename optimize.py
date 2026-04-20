"""
XAU_Scalper_EMA_RSI パラメータ最適化
  - ランダムサーチ 400 試行
  - ウォークフォワード検証 (70% IS / 30% OOS)
  - スコア = 純損益 / |最大DD| × ln(トレード数)  (回収率 × サンプル充実度)
"""

import numpy as np
import pandas as pd
import random
import time
from dataclasses import dataclass
from typing import Optional, List, Tuple

# ============================================================
# 探索空間 (各パラメータの候補値)
# ============================================================
SEARCH_SPACE = {
    "EMA_FAST":       [5, 7, 9, 12, 15],
    "EMA_SLOW":       [18, 21, 25, 30, 35],
    "RSI_BUY_MIN":    [45, 50, 52, 55, 58],
    "RSI_SELL_MAX":   [42, 45, 48, 50, 55],
    "ATR_MIN_POINTS": [50, 80, 100, 130, 160],
    "TAKE_PROFIT":    [300, 400, 500, 600, 800],
    "STOP_LOSS":      [150, 200, 250, 300, 400],
    "TRAILING_START": [100, 150, 200, 250],
    "TRAILING_STEP":  [50, 70, 100, 130],
}

# 固定パラメータ
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

N_TRIALS      = 400   # ランダムサーチ試行数
N_BARS        = 26000 # 約18日分 M1
IS_RATIO      = 0.70  # In-Sample 比率
MIN_TRADES    = 30    # 最低トレード数 (少なすぎるものを除外)
TOP_K         = 10    # 表示する上位件数

# ============================================================
# データ生成
# ============================================================
def generate_ohlcv(n: int, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    mu, sigma = 0.00005, 0.0008
    price = 2000.0
    closes = np.empty(n)
    closes[0] = price
    for i in range(1, n):
        closes[i] = closes[i-1] * (1 + rng.normal(mu, sigma))
    noise  = rng.uniform(0.05, 0.20, n)
    highs  = closes * (1 + noise * 0.0005)
    lows   = closes * (1 - noise * 0.0005)
    opens  = np.roll(closes, 1); opens[0] = closes[0]
    return pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes})

# ============================================================
# インジケーター計算 (numpy, 高速版)
# ============================================================
def calc_ema_np(arr: np.ndarray, period: int) -> np.ndarray:
    alpha  = 2.0 / (period + 1)
    result = np.empty_like(arr)
    result[0] = arr[0]
    for i in range(1, len(arr)):
        result[i] = alpha * arr[i] + (1 - alpha) * result[i-1]
    return result

def calc_rsi_np(arr: np.ndarray, period: int) -> np.ndarray:
    delta  = np.diff(arr, prepend=arr[0])
    gain   = np.where(delta > 0, delta, 0.0)
    loss   = np.where(delta < 0, -delta, 0.0)
    alpha  = 1.0 / period
    ag, al = np.empty_like(arr), np.empty_like(arr)
    ag[0]  = gain[0]; al[0] = loss[0]
    for i in range(1, len(arr)):
        ag[i] = alpha * gain[i] + (1 - alpha) * ag[i-1]
        al[i] = alpha * loss[i] + (1 - alpha) * al[i-1]
    rs  = np.where(al == 0, 100.0, ag / al)
    return 100.0 - (100.0 / (1.0 + rs))

def calc_atr_np(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
    prev_c = np.roll(close, 1); prev_c[0] = close[0]
    tr     = np.maximum(high - low,
             np.maximum(np.abs(high - prev_c), np.abs(low - prev_c)))
    alpha  = 1.0 / period
    atr    = np.empty_like(tr)
    atr[0] = tr[0]
    for i in range(1, len(tr)):
        atr[i] = alpha * tr[i] + (1 - alpha) * atr[i-1]
    return atr

def prepare_indicators(df: pd.DataFrame, p: dict) -> dict:
    c = df["close"].values
    return {
        "ema_fast": calc_ema_np(c, p["EMA_FAST"]),
        "ema_slow": calc_ema_np(c, p["EMA_SLOW"]),
        "rsi":      calc_rsi_np(c, p["RSI_PERIOD"]),
        "atr":      calc_atr_np(df["high"].values, df["low"].values, c, p["ATR_PERIOD"]),
    }

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

def backtest_core(df: pd.DataFrame, ind: dict, p: dict) -> List[float]:
    """トレード損益リストを返す"""
    high   = df["high"].values
    low    = df["low"].values
    close  = df["close"].values
    ef     = ind["ema_fast"]
    es     = ind["ema_slow"]
    rsi    = ind["rsi"]
    atr    = ind["atr"]
    POINT  = p["POINT"]
    LOT_V  = p["LOT_VALUE"]
    LOT_S  = p["LOT_SIZE"]
    TP     = p["TAKE_PROFIT"]
    SL     = p["STOP_LOSS"]
    TS     = p["TRAILING_START"]
    TSTEP  = p["TRAILING_STEP"]
    TRON   = p["TRAILING_ON"]
    COS    = p["CLOSE_ON_SIGNAL"]
    SPR    = p["SPREAD_POINTS"] * POINT
    MAX_SP = p["MAX_SPREAD"]
    ATR_TH = p["ATR_MIN_POINTS"]
    MCL    = p["MAX_CONSEC_LOSS"]
    CDN    = p["COOLDOWN_BARS"]
    RBM    = p["RSI_BUY_MIN"]
    RSM    = p["RSI_SELL_MAX"]

    warm   = p["EMA_SLOW"] + p["RSI_PERIOD"] + 5
    pos: Optional[Pos] = None
    trades: List[float] = []
    consec = 0
    cooldown = 0

    for i in range(warm, len(close)):
        bid = close[i]
        ask = bid + SPR

        # トレーリング
        if pos and TRON:
            if pos.direction == "buy":
                pp = (bid - pos.open_price) / POINT
                if pp >= TS:
                    nsl = bid - TSTEP * POINT
                    if nsl > pos.sl:
                        pos.sl = nsl
            else:
                pp = (pos.open_price - ask) / POINT
                if pp >= TS:
                    nsl = ask + TSTEP * POINT
                    if pos.sl == 0 or nsl < pos.sl:
                        pos.sl = nsl

        # TP/SL
        if pos:
            result = None
            if pos.direction == "buy":
                if low[i] <= pos.sl:
                    result = (pos.sl - pos.open_price) / POINT * LOT_V * LOT_S
                elif high[i] >= pos.tp:
                    result = (pos.tp  - pos.open_price) / POINT * LOT_V * LOT_S
            else:
                if high[i] >= pos.sl:
                    result = (pos.open_price - pos.sl) / POINT * LOT_V * LOT_S
                elif low[i] <= pos.tp:
                    result = (pos.open_price - pos.tp) / POINT * LOT_V * LOT_S

            if result is not None:
                trades.append(result)
                consec = consec + 1 if result < 0 else 0
                if consec >= MCL:
                    cooldown = i + CDN; consec = 0
                pos = None
                continue

        if i <= cooldown or p["SPREAD_POINTS"] > MAX_SP:
            continue

        j = i - 1  # 確定足
        if atr[j] / POINT < ATR_TH:
            continue

        bull = ef[j] > es[j]
        bear = ef[j] < es[j]
        rb   = rsi[j] >= RBM
        rs   = rsi[j] <= RSM
        buy  = bull and rb
        sell = bear and rs

        if pos:
            if COS:
                if pos.direction == "buy" and sell:
                    r = (bid - pos.open_price) / POINT * LOT_V * LOT_S
                    trades.append(r)
                    consec = consec + 1 if r < 0 else 0
                    if consec >= MCL: cooldown = i + CDN; consec = 0
                    pos = None
                elif pos.direction == "sell" and buy:
                    r = (pos.open_price - ask) / POINT * LOT_V * LOT_S
                    trades.append(r)
                    consec = consec + 1 if r < 0 else 0
                    if consec >= MCL: cooldown = i + CDN; consec = 0
                    pos = None
        else:
            if buy:
                pos = Pos("buy",  ask, ask - SL*POINT, ask + TP*POINT, i)
            elif sell:
                pos = Pos("sell", bid, bid + SL*POINT, bid - TP*POINT, i)

    return trades

def score(trades: List[float]) -> Tuple[float, dict]:
    if len(trades) < MIN_TRADES:
        return -999.0, {}
    t  = np.array(trades)
    eq = np.cumsum(t)
    net = eq[-1]
    dd  = float(np.min(eq - np.maximum.accumulate(eq)))
    if dd == 0:
        return -999.0, {}
    nw  = int((t > 0).sum())
    nl  = int((t <= 0).sum())
    gw  = float(t[t > 0].sum()) if nw else 0
    gl  = float(t[t <= 0].sum()) if nl else 1
    pf  = abs(gw / gl) if gl != 0 else 0
    wr  = nw / len(t) * 100
    sc  = (net / abs(dd)) * np.log1p(len(t))
    return sc, {"net": net, "dd": dd, "pf": pf, "wr": wr, "n": len(t)}

# ============================================================
# ランダムサーチ
# ============================================================
def random_params(seed=None) -> dict:
    rng = random.Random(seed)
    p = {k: rng.choice(v) for k, v in SEARCH_SPACE.items()}
    p.update(FIXED)
    # EMA_FAST < EMA_SLOW を強制
    if p["EMA_FAST"] >= p["EMA_SLOW"]:
        p["EMA_SLOW"] = p["EMA_FAST"] + rng.choice([9, 12, 15, 18])
    return p

def run_optimization(df: pd.DataFrame) -> List[dict]:
    n     = len(df)
    split = int(n * IS_RATIO)
    df_is = df.iloc[:split].reset_index(drop=True)
    df_oos= df.iloc[split:].reset_index(drop=True)

    results = []
    print(f"ランダムサーチ {N_TRIALS} 試行開始...")
    t0 = time.time()

    for trial in range(N_TRIALS):
        p   = random_params(trial)
        ind = prepare_indicators(df_is, p)
        tr  = backtest_core(df_is, ind, p)
        sc, stats = score(tr)
        if sc > -999:
            results.append({"params": p, "score": sc, "is": stats, "trial": trial})

        if (trial + 1) % 50 == 0:
            elapsed = time.time() - t0
            eta = elapsed / (trial+1) * (N_TRIALS - trial - 1)
            print(f"  [{trial+1:>4}/{N_TRIALS}] 有効={len(results)}件  経過{elapsed:.0f}s  残り{eta:.0f}s")

    print(f"\n完了 ({time.time()-t0:.1f}s) | 有効試行: {len(results)}/{N_TRIALS}\n")

    # 上位をOOS検証
    results.sort(key=lambda x: x["score"], reverse=True)
    top = results[:TOP_K]

    print("上位結果のOOS検証中...")
    for r in top:
        p   = r["params"]
        ind = prepare_indicators(df_oos, p)
        tr  = backtest_core(df_oos, ind, p)
        _, stats = score(tr)
        r["oos"] = stats if stats else {"net":0,"dd":0,"pf":0,"wr":0,"n":0}

    return top

# ============================================================
# レポート
# ============================================================
def print_report(top: List[dict]):
    print("=" * 72)
    print("  最適化結果 TOP", TOP_K)
    print(f"  {'#':<3} {'Score':>7} | {'IS 純損益':>9} {'IS PF':>6} {'IS 勝率':>7} {'IS N':>5} {'IS DD':>8} | {'OOS 損益':>8} {'OOS PF':>6} {'OOS N':>5}")
    print("-" * 72)
    for i, r in enumerate(top, 1):
        IS  = r["is"]
        OOS = r["oos"]
        print(f"  {i:<3} {r['score']:>7.2f} | "
              f"${IS['net']:>+8.2f} {IS['pf']:>6.2f} {IS['wr']:>6.1f}% {IS['n']:>5} ${IS['dd']:>+7.2f} | "
              f"${OOS['net']:>+7.2f} {OOS['pf']:>6.2f} {OOS['n']:>5}")
    print("=" * 72)

    best = top[0]
    p    = best["params"]
    IS   = best["is"]
    OOS  = best["oos"]

    print("\n  ★ 最優秀パラメータ (IS Score最高 + OOS確認済)")
    print("-" * 72)
    print(f"  EMA Fast/Slow     : {p['EMA_FAST']} / {p['EMA_SLOW']}")
    print(f"  RSI 買下限/売上限  : {p['RSI_BUY_MIN']} / {p['RSI_SELL_MAX']}")
    print(f"  ATR 最小閾値      : {p['ATR_MIN_POINTS']} points")
    print(f"  TP / SL           : {p['TAKE_PROFIT']} / {p['STOP_LOSS']} points")
    print(f"  Trailing Start/Step: {p['TRAILING_START']} / {p['TRAILING_STEP']} points")
    print()
    print(f"  [In-Sample  70%]  純損益 ${IS['net']:+.2f}  PF {IS['pf']:.2f}  勝率 {IS['wr']:.1f}%  {IS['n']}件  DD${IS['dd']:.2f}")
    print(f"  [Out-of-Sample 30%] 純損益 ${OOS['net']:+.2f}  PF {OOS['pf']:.2f}  勝率 {OOS['wr']:.1f}%  {OOS['n']}件  DD${OOS['dd']:.2f}")

    # OOS安定性: IS/OOS それぞれのバー数で正規化して比較
    is_bars  = int(N_BARS * IS_RATIO)
    oos_bars = N_BARS - is_bars
    is_per_bar  = IS["net"]  / is_bars  if is_bars  else 0
    oos_per_bar = OOS["net"] / oos_bars if oos_bars else 0
    if is_per_bar != 0:
        decay = (oos_per_bar - is_per_bar) / abs(is_per_bar) * 100
        print(f"\n  OOS vs IS (バー当たり損益比): {decay:+.1f}%  ", end="")
        if decay > -20:
            print("✓ 過学習リスク低")
        elif decay > -50:
            print("△ やや過学習の可能性あり")
        else:
            print("✗ 過学習の疑いあり — 慎重に")

    print()
    print("  ── EAへの反映 (XAU_Scalper_EMA_RSI.mq5 推奨値) ─────────────────")
    print(f"  InpEmaFast      = {p['EMA_FAST']}")
    print(f"  InpEmaSlow      = {p['EMA_SLOW']}")
    print(f"  InpRsiBuyMin    = {p['RSI_BUY_MIN']}")
    print(f"  InpRsiSellMax   = {p['RSI_SELL_MAX']}")
    print(f"  InpAtrMinPoints = {p['ATR_MIN_POINTS']}")
    print(f"  InpTakeProfit   = {p['TAKE_PROFIT']}")
    print(f"  InpStopLoss     = {p['STOP_LOSS']}")
    print(f"  InpTrailingStart= {p['TRAILING_START']}")
    print(f"  InpTrailingStep = {p['TRAILING_STEP']}")
    print("=" * 72)

# ============================================================
# メイン
# ============================================================
if __name__ == "__main__":
    print(f"データ生成: {N_BARS}バー (M1相当 約{N_BARS//60//24}日分)")
    df   = generate_ohlcv(N_BARS)
    top  = run_optimization(df)
    print_report(top)
