"""
EMA10 × 15分足 × ローソク足パターン 戦略

元ネタ: https://x.com/cora64189920179/status/2039688312022024289

ルール (ロングの場合):
  1) ローソク足の終値が EMA10 を下から上に抜けて確定 (ブレイク)
  2) その後、終値が EMA10 の上を維持した状態でローソク足が EMA10 にタッチ
     (= その足の安値 <= EMA10 <= 高値)
  3) タッチした足が以下 4 パターンのいずれかであること
       - 上昇ピンバー  (下ヒゲが長い陽線)
       - 上昇継続 1/2/3 (しっかりした陽線)
  4) 次の足の始値でロングエントリー
  5) 利確 = 直近高値  /  損切り = 直近安値

ショートは上記の反対。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd


Side = Literal["long", "short"]


# ---------------------------------------------------------------------------
# インジケーター
# ---------------------------------------------------------------------------
def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """True Range の指数移動平均 (Wilder の代わりに EMA を使用)。"""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


# ---------------------------------------------------------------------------
# ローソク足パターン判定
# ---------------------------------------------------------------------------
def _body(o: float, c: float) -> float:
    return abs(c - o)


def _upper_wick(o: float, h: float, c: float) -> float:
    return h - max(o, c)


def _lower_wick(o: float, l: float, c: float) -> float:
    return min(o, c) - l


def is_bullish_pinbar(o: float, h: float, l: float, c: float) -> bool:
    """下ヒゲが本体の 2 倍以上あり、上ヒゲが本体以下の陽線。"""
    body = _body(o, c)
    if body <= 0:
        # 十字線寄りの場合、レンジで判定
        rng = h - l
        if rng <= 0:
            return False
        return (min(o, c) - l) >= rng * 0.6 and (h - max(o, c)) <= rng * 0.2
    return (
        c >= o
        and _lower_wick(o, l, c) >= body * 2.0
        and _upper_wick(o, h, c) <= body * 1.0
    )


def is_bearish_pinbar(o: float, h: float, l: float, c: float) -> bool:
    """上ヒゲが本体の 2 倍以上あり、下ヒゲが本体以下の陰線。"""
    body = _body(o, c)
    if body <= 0:
        rng = h - l
        if rng <= 0:
            return False
        return (h - max(o, c)) >= rng * 0.6 and (min(o, c) - l) <= rng * 0.2
    return (
        c <= o
        and _upper_wick(o, h, c) >= body * 2.0
        and _lower_wick(o, l, c) <= body * 1.0
    )


def is_bullish_continuation(o: float, h: float, l: float, c: float) -> bool:
    """しっかりした陽線 (実体がレンジの 50% 以上、下ヒゲが実体より短い)。"""
    if c <= o:
        return False
    rng = h - l
    if rng <= 0:
        return False
    body = c - o
    return body / rng >= 0.5 and _lower_wick(o, l, c) <= body


def is_bearish_continuation(o: float, h: float, l: float, c: float) -> bool:
    """しっかりした陰線 (実体がレンジの 50% 以上、上ヒゲが実体より短い)。"""
    if c >= o:
        return False
    rng = h - l
    if rng <= 0:
        return False
    body = o - c
    return body / rng >= 0.5 and _upper_wick(o, h, c) <= body


def bullish_entry_pattern(o: float, h: float, l: float, c: float) -> bool:
    """タッチ足が許容されるロング用パターンか (ピンバー or 継続陽線)。"""
    return is_bullish_pinbar(o, h, l, c) or is_bullish_continuation(o, h, l, c)


def bearish_entry_pattern(o: float, h: float, l: float, c: float) -> bool:
    return is_bearish_pinbar(o, h, l, c) or is_bearish_continuation(o, h, l, c)


# ---------------------------------------------------------------------------
# シグナル生成
# ---------------------------------------------------------------------------
@dataclass
class Signal:
    index: int          # シグナルが発生した足のインデックス (= タッチ足)
    side: Side          # "long" or "short"
    entry_index: int    # 実際にエントリーする足 (= index + 1)
    entry_price: float  # その次の足の始値
    stop: float         # 直近安値 (long) / 直近高値 (short)
    take: float         # 直近高値 (long) / 直近安値 (short)


def _resolve_levels(
    side: Side,
    entry_price: float,
    recent_high: float,
    recent_low: float,
    atr_value: float,
    sl_mode: str,
    tp_mode: str,
    rr_ratio: float,
    atr_mult_sl: float,
    atr_mult_tp: float,
) -> tuple[float, float] | None:
    """エントリー価格と参照値から (stop, take) を決定する。"""
    # ----- SL -----
    if sl_mode == "swing":
        stop = recent_low if side == "long" else recent_high
    elif sl_mode == "atr":
        if not np.isfinite(atr_value) or atr_value <= 0:
            return None
        stop = entry_price - atr_mult_sl * atr_value if side == "long" else entry_price + atr_mult_sl * atr_value
    else:
        raise ValueError(f"unknown sl_mode: {sl_mode}")

    # SL がエントリーの正しい側にあるか
    if side == "long" and stop >= entry_price:
        return None
    if side == "short" and stop <= entry_price:
        return None

    risk = abs(entry_price - stop)
    if risk <= 0:
        return None

    # ----- TP -----
    if tp_mode == "swing":
        take = recent_high if side == "long" else recent_low
    elif tp_mode == "rr":
        take = entry_price + rr_ratio * risk if side == "long" else entry_price - rr_ratio * risk
    elif tp_mode == "atr":
        if not np.isfinite(atr_value) or atr_value <= 0:
            return None
        take = entry_price + atr_mult_tp * atr_value if side == "long" else entry_price - atr_mult_tp * atr_value
    else:
        raise ValueError(f"unknown tp_mode: {tp_mode}")

    if side == "long" and take <= entry_price:
        return None
    if side == "short" and take >= entry_price:
        return None

    return stop, take


def generate_signals(
    df: pd.DataFrame,
    ema_period: int = 10,
    swing_lookback: int = 20,
    sl_mode: str = "swing",
    tp_mode: str = "swing",
    rr_ratio: float = 2.0,
    atr_period: int = 14,
    atr_mult_sl: float = 1.5,
    atr_mult_tp: float = 3.0,
) -> list[Signal]:
    """
    OHLC データからシグナルを生成する。

    Parameters
    ----------
    df : DataFrame
        必要カラム: open, high, low, close  (index は時刻)
    ema_period : int
        EMA の期間。デフォルト 10。
    swing_lookback : int
        直近高値/安値を計算する際の参照本数。
    sl_mode : "swing" | "atr"
        損切モード。
    tp_mode : "swing" | "rr" | "atr"
        利確モード。"rr" は SL までの距離 × rr_ratio。
    rr_ratio : float
        tp_mode="rr" のときのリスクリワード比 (例: 2.0)。
    atr_period, atr_mult_sl, atr_mult_tp : float
        ATR ベースモード用パラメータ。
    """
    required = {"open", "high", "low", "close"}
    if not required.issubset(df.columns):
        raise ValueError(f"df must contain columns {required}, got {df.columns.tolist()}")

    df = df.copy()
    df["ema"] = ema(df["close"], ema_period)
    df["atr"] = atr(df, atr_period)

    o_arr = df["open"].to_numpy()
    h_arr = df["high"].to_numpy()
    l_arr = df["low"].to_numpy()
    c_arr = df["close"].to_numpy()
    e_arr = df["ema"].to_numpy()
    a_arr = df["atr"].to_numpy()

    signals: list[Signal] = []

    # 状態: None / "above" (EMA上でリテスト待ち) / "below" (EMA下でリテスト待ち)
    state: str | None = None

    for i in range(1, len(df) - 1):  # エントリーは次足なので最後の足は除外
        if np.isnan(e_arr[i]):
            continue

        prev_close = c_arr[i - 1]
        prev_ema = e_arr[i - 1]
        curr_close = c_arr[i]
        curr_ema = e_arr[i]

        # --- ブレイク検知 ---
        crossed_up = prev_close <= prev_ema and curr_close > curr_ema
        crossed_dn = prev_close >= prev_ema and curr_close < curr_ema
        if crossed_up:
            state = "above"
            continue
        if crossed_dn:
            state = "below"
            continue

        # --- リテスト + パターン判定 ---
        if state == "above":
            if curr_close <= curr_ema:
                state = None
                continue
            touched = l_arr[i] <= curr_ema
            if touched and bullish_entry_pattern(o_arr[i], h_arr[i], l_arr[i], c_arr[i]):
                lo = max(0, i - swing_lookback)
                recent_high = float(np.max(h_arr[lo : i + 1]))
                recent_low = float(np.min(l_arr[lo : i + 1]))
                entry_price = float(o_arr[i + 1])
                levels = _resolve_levels(
                    "long", entry_price, recent_high, recent_low, float(a_arr[i]),
                    sl_mode, tp_mode, rr_ratio, atr_mult_sl, atr_mult_tp,
                )
                if levels is not None:
                    stop, take = levels
                    signals.append(
                        Signal(
                            index=i,
                            side="long",
                            entry_index=i + 1,
                            entry_price=entry_price,
                            stop=stop,
                            take=take,
                        )
                    )
                    state = None

        elif state == "below":
            if curr_close >= curr_ema:
                state = None
                continue
            touched = h_arr[i] >= curr_ema
            if touched and bearish_entry_pattern(o_arr[i], h_arr[i], l_arr[i], c_arr[i]):
                lo = max(0, i - swing_lookback)
                recent_high = float(np.max(h_arr[lo : i + 1]))
                recent_low = float(np.min(l_arr[lo : i + 1]))
                entry_price = float(o_arr[i + 1])
                levels = _resolve_levels(
                    "short", entry_price, recent_high, recent_low, float(a_arr[i]),
                    sl_mode, tp_mode, rr_ratio, atr_mult_sl, atr_mult_tp,
                )
                if levels is not None:
                    stop, take = levels
                    signals.append(
                        Signal(
                            index=i,
                            side="short",
                            entry_index=i + 1,
                            entry_price=entry_price,
                            stop=stop,
                            take=take,
                        )
                    )
                    state = None

    return signals
