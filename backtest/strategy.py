"""EMA + RSI + ATR scalping strategy (crypto-adapted, ATR-proportional exits).

MT5版 CryptoScalper_EMA_RSI_ATR.mq5 と同じロジックを Python で再現。
バックテスト/最適化用。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator

import numpy as np
import pandas as pd


# --------------------------- Indicators ---------------------------

def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0.0)
    dn = (-delta).clip(lower=0.0)
    roll_up = up.ewm(alpha=1.0 / n, adjust=False).mean()
    roll_dn = dn.ewm(alpha=1.0 / n, adjust=False).mean()
    rs = roll_up / roll_dn.replace(0.0, np.nan)
    out = 100.0 - 100.0 / (1.0 + rs)
    return out.fillna(50.0)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l).abs(), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False).mean()


def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Wilder's ADX. トレンド強度 (0-100, >25 = トレンドあり)."""
    h, l, c = df["high"], df["low"], df["close"]
    up = h.diff()
    dn = -l.diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    pc = c.shift(1)
    tr = pd.concat([(h - l).abs(), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr_w = tr.ewm(alpha=1.0 / n, adjust=False).mean()
    plus_di = 100.0 * pd.Series(plus_dm, index=df.index).ewm(alpha=1.0/n, adjust=False).mean() / atr_w
    minus_di = 100.0 * pd.Series(minus_dm, index=df.index).ewm(alpha=1.0/n, adjust=False).mean() / atr_w
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    return dx.ewm(alpha=1.0 / n, adjust=False).mean().fillna(0.0)


def htf_trend(close: pd.Series, htf_ratio: int, fast: int, slow: int) -> pd.Series:
    """上位足 EMA トレンド方向 (+1 up / -1 down / 0 flat-or-na).
    htf_ratio: 現在TFを何倍にリサンプリングするか (0 or 1 = 無効)."""
    if htf_ratio <= 1:
        return pd.Series(0, index=close.index)
    rs = close.resample(f"{htf_ratio}min" if False else _infer_htf(close, htf_ratio)).last().dropna()
    ef = ema(rs, fast)
    es = ema(rs, slow)
    direction = pd.Series(0, index=rs.index, dtype=int)
    direction[ef > es] = 1
    direction[ef < es] = -1
    return direction.reindex(close.index, method="ffill").fillna(0).astype(int)


def _infer_htf(close: pd.Series, ratio: int) -> str:
    """現在足の周期を index から推定して上位足 freq を返す."""
    if len(close.index) < 2:
        return f"{ratio}min"
    # 最頻値ベース
    diffs = close.index.to_series().diff().dropna()
    base_min = int(round(diffs.dt.total_seconds().median() / 60))
    return f"{base_min * ratio}min"


# --------------------------- Params ---------------------------

@dataclass
class Params:
    ema_fast: int = 20
    ema_slow: int = 50
    rsi_period: int = 14
    rsi_buy_min: float = 50.0
    rsi_sell_max: float = 50.0
    atr_period: int = 14
    atr_min_mult: float = 1.0       # 直近20本ATR平均との比較
    tp_atr_mult: float = 4.0
    sl_atr_mult: float = 1.0
    trail_start_atr: float = 0.5
    trail_step_atr: float = 0.3
    close_on_signal: bool = True
    max_consec_loss: int = 3
    cooldown_bars: int = 24          # 24本（M5=2h, M15=6h, H1=24h）
    # --- トレンドフォロー強化 (新) ---
    adx_period: int = 14
    adx_min: float = 0.0             # >0 で ADX フィルタ有効 (推奨 20-30)
    htf_ratio: int = 0               # >1 で上位足 EMA フィルタ有効 (e.g. 4=H1 from M15)
    htf_ema_fast: int = 20
    htf_ema_slow: int = 50
    trail_only: bool = False         # True なら TP 無視, トレールで決済
    risk_pct: float = 0.0            # 0なら固定ロット (デフォは固定の方が解釈しやすい)
    fixed_qty: float = 0.01          # BTC 単位 (Bitget)
    # Bitget 想定の手数料/スリッページ
    fee_rt_pct: float = 0.12         # 往復 0.12% (taker両側)
    slippage_pct: float = 0.02       # 片側 0.02%
    # 資金モデル
    initial_balance: float = 10_000.0


@dataclass
class Trade:
    side: str            # "long"/"short"
    entry_time: pd.Timestamp
    entry: float
    qty: float
    sl: float
    tp: float
    exit_time: pd.Timestamp | None = None
    exit: float | None = None
    pnl: float = 0.0
    reason: str = ""


# --------------------------- Backtest ---------------------------

@dataclass
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    equity: pd.Series = field(default_factory=pd.Series)

    def metrics(self) -> dict:
        if not self.trades:
            return dict(n=0, pf=0.0, win=0.0, ret=0.0, max_dd=0.0, sharpe=0.0,
                        avg=0.0, expectancy=0.0)
        pnls = np.array([t.pnl for t in self.trades])
        wins = pnls[pnls > 0].sum()
        losses = -pnls[pnls < 0].sum()
        pf = wins / losses if losses > 0 else float("inf")
        win = float((pnls > 0).mean())
        ret_pct = (self.equity.iloc[-1] / self.equity.iloc[0] - 1.0) * 100.0
        # Max drawdown
        peak = self.equity.cummax()
        dd = (self.equity - peak) / peak
        max_dd = float(dd.min() * 100.0)
        # Sharpe (per-trade)
        sharpe = float(pnls.mean() / pnls.std() * np.sqrt(252)) if pnls.std() > 0 else 0.0
        return dict(
            n=len(self.trades),
            pf=round(float(pf), 3),
            win=round(win * 100.0, 2),
            ret=round(ret_pct, 2),
            max_dd=round(max_dd, 2),
            sharpe=round(sharpe, 3),
            avg=round(float(pnls.mean()), 4),
            expectancy=round(float(pnls.mean()), 4),
        )


def prepare(df: pd.DataFrame, p: Params) -> pd.DataFrame:
    out = df.copy()
    out["ema_f"] = ema(out["close"], p.ema_fast)
    out["ema_s"] = ema(out["close"], p.ema_slow)
    out["rsi"] = rsi(out["close"], p.rsi_period)
    out["atr"] = atr(out, p.atr_period)
    out["atr_avg20"] = out["atr"].rolling(20, min_periods=5).mean()
    out["adx"] = adx(out, p.adx_period) if p.adx_min > 0 else 100.0
    if p.htf_ratio > 1:
        out["htf_dir"] = htf_trend(out["close"], p.htf_ratio,
                                   p.htf_ema_fast, p.htf_ema_slow)
    else:
        out["htf_dir"] = 0
    return out


def backtest(df: pd.DataFrame, p: Params) -> BacktestResult:
    """Bar-close decision, next-bar-open execution. Bitget 手数料/スリッページ込み."""
    d = prepare(df, p)
    balance = p.initial_balance
    equity_pts: list[tuple[pd.Timestamp, float]] = []
    trades: list[Trade] = []
    open_trade: Trade | None = None
    consec_losses = 0
    cooldown_until_bar = -1
    bar_idx = 0

    fee_each = p.fee_rt_pct / 200.0       # 片側ぶん (％→小数)
    slip = p.slippage_pct / 100.0

    rows = d.itertuples(index=True)
    prev = next(rows, None)
    if prev is None:
        return BacktestResult()

    for r in rows:
        bar_idx += 1
        ts = r.Index
        # ---- 既存ポジションの管理（このバーの high/low で SL/TP/トレール判定）----
        if open_trade is not None:
            high, low = r.high, r.low
            t = open_trade
            atr_now = r.atr if not np.isnan(r.atr) else 0.0
            trail_start = atr_now * p.trail_start_atr
            trail_step  = atr_now * p.trail_step_atr

            if t.side == "long":
                # トレーリング更新（高値ベース）
                profit = high - t.entry
                if trail_start > 0 and profit >= trail_start:
                    new_sl = high - trail_step
                    if new_sl > t.sl:
                        t.sl = new_sl
                # SL/TP 判定（保守的に SL 優先）
                if low <= t.sl:
                    exit_px = t.sl * (1.0 - slip)
                    pnl = (exit_px - t.entry) * t.qty - (t.entry + exit_px) * t.qty * fee_each
                    t.exit, t.exit_time, t.pnl, t.reason = exit_px, ts, pnl, "SL"
                elif high >= t.tp:
                    exit_px = t.tp * (1.0 - slip)
                    pnl = (exit_px - t.entry) * t.qty - (t.entry + exit_px) * t.qty * fee_each
                    t.exit, t.exit_time, t.pnl, t.reason = exit_px, ts, pnl, "TP"
            else:  # short
                profit = t.entry - low
                if trail_start > 0 and profit >= trail_start:
                    new_sl = low + trail_step
                    if t.sl == 0 or new_sl < t.sl:
                        t.sl = new_sl
                if high >= t.sl:
                    exit_px = t.sl * (1.0 + slip)
                    pnl = (t.entry - exit_px) * t.qty - (t.entry + exit_px) * t.qty * fee_each
                    t.exit, t.exit_time, t.pnl, t.reason = exit_px, ts, pnl, "SL"
                elif low <= t.tp:
                    exit_px = t.tp * (1.0 + slip)
                    pnl = (t.entry - exit_px) * t.qty - (t.entry + exit_px) * t.qty * fee_each
                    t.exit, t.exit_time, t.pnl, t.reason = exit_px, ts, pnl, "TP"

            if t.exit is not None:
                balance += t.pnl
                trades.append(t)
                if t.pnl < 0:
                    consec_losses += 1
                    if consec_losses >= p.max_consec_loss:
                        cooldown_until_bar = bar_idx + p.cooldown_bars
                        consec_losses = 0
                elif t.pnl > 0:
                    consec_losses = 0
                open_trade = None

        equity_pts.append((ts, balance))

        # ---- 新規シグナル（前バー確定値で判定、現バー始値で約定）----
        if open_trade is not None:
            prev = r
            continue
        if bar_idx < cooldown_until_bar:
            prev = r
            continue
        if (np.isnan(prev.ema_f) or np.isnan(prev.ema_s) or np.isnan(prev.atr)
                or np.isnan(prev.atr_avg20) or prev.atr_avg20 == 0):
            prev = r
            continue

        vol_ok = prev.atr >= prev.atr_avg20 * p.atr_min_mult
        adx_ok = (p.adx_min <= 0) or (getattr(prev, "adx", 100.0) >= p.adx_min)
        htf_dir = int(getattr(prev, "htf_dir", 0))
        htf_long_ok  = (p.htf_ratio <= 1) or (htf_dir >= 0)   # 0=未確定でも許可、-1で禁止
        htf_short_ok = (p.htf_ratio <= 1) or (htf_dir <= 0)
        buy  = ((prev.ema_f > prev.ema_s) and (prev.rsi >= p.rsi_buy_min)
                and vol_ok and adx_ok and htf_long_ok)
        sell = ((prev.ema_f < prev.ema_s) and (prev.rsi <= p.rsi_sell_max)
                and vol_ok and adx_ok and htf_short_ok)

        if buy or sell:
            entry_raw = r.open
            atr_e = prev.atr
            tp_d, sl_d = atr_e * p.tp_atr_mult, atr_e * p.sl_atr_mult
            if p.risk_pct > 0:
                risk_money = balance * p.risk_pct / 100.0
                qty = max(p.fixed_qty * 0.1, risk_money / max(sl_d, 1e-9))
            else:
                qty = p.fixed_qty
            # trail_only=True なら TP を遠くへ追いやって実質無効化
            if p.trail_only:
                tp_d = atr_e * 1e6
            if buy:
                entry = entry_raw * (1.0 + slip)
                open_trade = Trade("long", ts, entry, qty, entry - sl_d, entry + tp_d)
            else:
                entry = entry_raw * (1.0 - slip)
                open_trade = Trade("short", ts, entry, qty, entry + sl_d, entry - tp_d)
        prev = r

    # 残ポジは最終バー終値で強制決済
    if open_trade is not None:
        last = d.iloc[-1]
        exit_px = last.close
        t = open_trade
        if t.side == "long":
            t.pnl = (exit_px - t.entry) * t.qty - (t.entry + exit_px) * t.qty * fee_each
        else:
            t.pnl = (t.entry - exit_px) * t.qty - (t.entry + exit_px) * t.qty * fee_each
        t.exit, t.exit_time, t.reason = exit_px, last.name, "EOD"
        trades.append(t)
        balance += t.pnl
        equity_pts.append((last.name, balance))

    eq = pd.Series({ts: v for ts, v in equity_pts}).sort_index()
    return BacktestResult(trades=trades, equity=eq)
