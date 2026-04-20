"""
XAU_Scalper_EMA_RSI バックテスト (EAロジック完全再現)
XAUUSD M1 相当の合成価格データで検証
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional

# ============================================================
# パラメータ (EAと同一)
# ============================================================
LOT_SIZE        = 0.01
TAKE_PROFIT     = 500      # points (1 point = $0.01 for XAUUSD)
STOP_LOSS       = 300
MAX_SPREAD      = 50
EMA_FAST        = 9
EMA_SLOW        = 21
RSI_PERIOD      = 14
RSI_BUY_MIN     = 50.0
RSI_SELL_MAX    = 50.0
ATR_PERIOD      = 14
ATR_MIN_POINTS  = 100.0
TRAILING_ON     = True
TRAILING_START  = 150
TRAILING_STEP   = 80
CLOSE_ON_SIGNAL = True
MAX_CONSEC_LOSS = 3
COOLDOWN_BARS   = 30       # 1800秒 ≒ 30バー (M1)
SPREAD_POINTS   = 20       # 固定スプレッド想定
POINT           = 0.01     # XAUUSD 1 point
LOT_VALUE       = 1.0      # XAUUSD: 1 lot = $1/point → 0.01 lot = $0.01/point

# ============================================================
# データ生成 (XAUUSD M1 GBM相当, 約3ヶ月分)
# ============================================================
def generate_ohlcv(n_bars: int = 13000, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    mu    = 0.0001      # drift per bar
    sigma = 0.0008      # volatility per bar

    price = 2000.0
    closes = [price]
    for _ in range(n_bars - 1):
        ret   = rng.normal(mu, sigma)
        price = price * (1 + ret)
        closes.append(price)

    closes = np.array(closes)
    noise  = rng.uniform(0.05, 0.15, n_bars)
    highs  = closes + closes * noise * 0.001
    lows   = closes - closes * noise * 0.001
    opens  = np.roll(closes, 1)
    opens[0] = closes[0]

    idx = pd.date_range("2024-01-01", periods=n_bars, freq="1min")
    return pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes}, index=idx)

# ============================================================
# インジケーター計算
# ============================================================
def calc_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def calc_rsi(series: pd.Series, period: int) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def calc_atr(df: pd.DataFrame, period: int) -> pd.Series:
    hl  = df["high"] - df["low"]
    hc  = (df["high"] - df["close"].shift()).abs()
    lc  = (df["low"]  - df["close"].shift()).abs()
    tr  = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()

# ============================================================
# ポジション
# ============================================================
@dataclass
class Position:
    direction: str          # "buy" / "sell"
    open_price: float
    sl: float
    tp: float
    open_bar: int
    trailing_sl: float = 0.0

# ============================================================
# バックテストエンジン
# ============================================================
def run_backtest(df: pd.DataFrame) -> dict:
    df = df.copy()
    df["ema_fast"] = calc_ema(df["close"], EMA_FAST)
    df["ema_slow"] = calc_ema(df["close"], EMA_SLOW)
    df["rsi"]      = calc_rsi(df["close"], RSI_PERIOD)
    df["atr"]      = calc_atr(df, ATR_PERIOD)

    pos: Optional[Position] = None
    trades = []
    consec_loss   = 0
    cooldown_until = 0

    for i in range(EMA_SLOW + RSI_PERIOD + 5, len(df)):
        row   = df.iloc[i]
        prev  = df.iloc[i - 1]      # 確定足 (バー1相当)
        price = row["close"]
        bid   = price
        ask   = price + SPREAD_POINTS * POINT

        # ---- トレーリングストップ (毎バー) ----
        if pos and TRAILING_ON:
            if pos.direction == "buy":
                profit_pts = (bid - pos.open_price) / POINT
                if profit_pts >= TRAILING_START:
                    new_sl = bid - TRAILING_STEP * POINT
                    if new_sl > pos.sl:
                        pos.sl = new_sl
            else:
                profit_pts = (pos.open_price - ask) / POINT
                if profit_pts >= TRAILING_START:
                    new_sl = ask + TRAILING_STEP * POINT
                    if pos.sl == 0 or new_sl < pos.sl:
                        pos.sl = new_sl

        # ---- TP/SL チェック ----
        if pos:
            closed = False
            result = 0.0
            if pos.direction == "buy":
                if row["low"] <= pos.sl:
                    result = (pos.sl - pos.open_price) / POINT * LOT_VALUE * LOT_SIZE
                    closed = True; close_reason = "SL"
                elif row["high"] >= pos.tp:
                    result = (pos.tp - pos.open_price) / POINT * LOT_VALUE * LOT_SIZE
                    closed = True; close_reason = "TP"
            else:
                if row["high"] >= pos.sl:
                    result = (pos.open_price - pos.sl) / POINT * LOT_VALUE * LOT_SIZE
                    closed = True; close_reason = "SL"
                elif row["low"] <= pos.tp:
                    result = (pos.open_price - pos.tp) / POINT * LOT_VALUE * LOT_SIZE
                    closed = True; close_reason = "TP"

            if closed:
                trades.append({"bar": i, "result": result, "reason": close_reason,
                               "dir": pos.direction, "duration": i - pos.open_bar})
                consec_loss = (consec_loss + 1) if result < 0 else 0
                if consec_loss >= MAX_CONSEC_LOSS:
                    cooldown_until = i + COOLDOWN_BARS
                    consec_loss = 0
                pos = None
                continue

        # ---- 新バー判定ロジック (確定足=prev) ----
        if i <= cooldown_until:
            continue
        if SPREAD_POINTS > MAX_SPREAD:
            continue

        atr_pts = prev["atr"] / POINT
        if atr_pts < ATR_MIN_POINTS:
            continue

        ema_bull = prev["ema_fast"] > prev["ema_slow"]
        ema_bear = prev["ema_fast"] < prev["ema_slow"]
        rsi_buy  = prev["rsi"] >= RSI_BUY_MIN
        rsi_sell = prev["rsi"] <= RSI_SELL_MAX

        buy_signal  = ema_bull and rsi_buy
        sell_signal = ema_bear and rsi_sell

        if pos:
            if CLOSE_ON_SIGNAL:
                if pos.direction == "buy" and sell_signal:
                    result = (bid - pos.open_price) / POINT * LOT_VALUE * LOT_SIZE
                    trades.append({"bar": i, "result": result, "reason": "RevSig",
                                   "dir": pos.direction, "duration": i - pos.open_bar})
                    consec_loss = (consec_loss + 1) if result < 0 else 0
                    if consec_loss >= MAX_CONSEC_LOSS:
                        cooldown_until = i + COOLDOWN_BARS; consec_loss = 0
                    pos = None
                elif pos.direction == "sell" and buy_signal:
                    result = (pos.open_price - ask) / POINT * LOT_VALUE * LOT_SIZE
                    trades.append({"bar": i, "result": result, "reason": "RevSig",
                                   "dir": pos.direction, "duration": i - pos.open_bar})
                    consec_loss = (consec_loss + 1) if result < 0 else 0
                    if consec_loss >= MAX_CONSEC_LOSS:
                        cooldown_until = i + COOLDOWN_BARS; consec_loss = 0
                    pos = None
        else:
            if buy_signal:
                sl = ask - STOP_LOSS   * POINT
                tp = ask + TAKE_PROFIT * POINT
                pos = Position("buy", ask, sl, tp, i)
            elif sell_signal:
                sl = bid + STOP_LOSS   * POINT
                tp = bid - TAKE_PROFIT * POINT
                pos = Position("sell", bid, sl, tp, i)

    return {"trades": trades, "df": df}

# ============================================================
# 結果集計・表示
# ============================================================
def print_report(result: dict):
    trades = result["trades"]
    if not trades:
        print("トレードなし")
        return

    t = pd.DataFrame(trades)
    profits = t["result"]

    total      = profits.sum()
    n_total    = len(t)
    n_win      = (profits > 0).sum()
    n_loss     = (profits <= 0).sum()
    win_rate   = n_win / n_total * 100
    avg_win    = profits[profits > 0].mean() if n_win else 0
    avg_loss   = profits[profits <= 0].mean() if n_loss else 0
    pf         = abs(profits[profits > 0].sum() / profits[profits <= 0].sum()) if n_loss else float("inf")
    max_dd     = calc_max_drawdown(profits)
    avg_dur    = t["duration"].mean()

    by_reason  = t.groupby("reason")["result"].agg(["count", "sum", "mean"])

    print("=" * 52)
    print("  XAU_Scalper_EMA_RSI  バックテスト結果")
    print("=" * 52)
    print(f"  総トレード数  : {n_total:>6}")
    print(f"  勝ち          : {n_win:>6}  ({win_rate:.1f}%)")
    print(f"  負け          : {n_loss:>6}")
    print(f"  純損益        : ${total:>+8.2f}")
    print(f"  プロフィットF : {pf:>8.2f}")
    print(f"  平均利益      : ${avg_win:>+8.2f}")
    print(f"  平均損失      : ${avg_loss:>+8.2f}")
    print(f"  最大DD        : ${max_dd:>8.2f}")
    print(f"  平均保有バー  : {avg_dur:>6.1f} 本")
    print()
    print("  ── 決済理由別 ──────────────────────────")
    for reason, row in by_reason.iterrows():
        print(f"  {reason:<8}: {int(row['count']):>4}件  合計${row['sum']:>+8.2f}  平均${row['mean']:>+7.2f}")

    # 月別損益
    df = result["df"]
    t["date"] = [df.index[b] for b in t["bar"]]
    t["month"] = pd.to_datetime(t["date"]).dt.to_period("M")
    monthly = t.groupby("month")["result"].sum()
    print()
    print("  ── 月別損益 ─────────────────────────────")
    for m, v in monthly.items():
        bar = "█" * int(abs(v) / 0.5) if abs(v) > 0 else ""
        sign = "+" if v >= 0 else ""
        print(f"  {m}  ${sign}{v:.2f}  {bar}")
    print("=" * 52)

def calc_max_drawdown(profits: pd.Series) -> float:
    equity = profits.cumsum()
    peak   = equity.cummax()
    dd     = (equity - peak)
    return dd.min()

# ============================================================
# エントリー
# ============================================================
if __name__ == "__main__":
    print("データ生成中...")
    df = generate_ohlcv(n_bars=13000)
    print(f"バー数: {len(df)} (約{len(df)/60/24:.0f}日分, M1相当)")
    print("バックテスト実行中...\n")

    result = run_backtest(df)
    print_report(result)
