"""
ヒストリカルデータのローダー。

優先順位:
  1) CSV ファイル (--csv で指定)
  2) yfinance (インターネット経由。XAU/USD は "GC=F" で取得可能)
  3) 上記が使えない環境のためのダミー生成 (再現可能な乱数ウォーク)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


REQUIRED = ["open", "high", "low", "close"]


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={c: c.lower() for c in df.columns})
    # yfinance は "Adj Close" など余分な列を含むことがある
    for col in REQUIRED:
        if col not in df.columns:
            raise ValueError(f"column '{col}' not found in data (got {df.columns.tolist()})")
    df = df[REQUIRED].copy()
    df = df.dropna()
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    return df


def load_csv(path: str | Path) -> pd.DataFrame:
    """CSV から読み込む。1 列目を時刻として扱う。"""
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    return _normalize(df)


def load_yfinance(
    ticker: str = "GC=F",
    period: str = "60d",
    interval: str = "15m",
) -> pd.DataFrame:
    """
    yfinance 経由で取得。XAU/USD 代替として COMEX 金先物 'GC=F' を使用。
    15 分足は過去 60 日程度しか取れない点に注意。
    """
    try:
        import yfinance as yf  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "yfinance not installed. Run: pip install yfinance"
        ) from e

    df = yf.download(
        ticker,
        period=period,
        interval=interval,
        progress=False,
        auto_adjust=False,
    )
    if df is None or df.empty:
        raise RuntimeError(f"yfinance returned no data for {ticker}")
    # MultiIndex columns (新しい yfinance) 対策
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    return _normalize(df)


def synthetic_gold_15m(
    n_bars: int = 4000,
    seed: int = 42,
    start_price: float = 2000.0,
) -> pd.DataFrame:
    """
    オフライン検証用のダミー 15 分足データ。
    トレンドの入れ替わるランダムウォークを生成する。
    """
    rng = np.random.default_rng(seed)

    # トレンドレジームを切り替える
    regime_len = 200
    drift_values = rng.choice([-0.08, 0.0, 0.08], size=(n_bars // regime_len + 1))
    drifts = np.repeat(drift_values, regime_len)[:n_bars]

    vol = 0.5  # 1 bar あたり標準偏差
    rets = rng.normal(loc=drifts, scale=vol, size=n_bars)

    close = start_price + np.cumsum(rets)
    # OHLC を近似的に作る
    open_ = np.empty(n_bars)
    open_[0] = start_price
    open_[1:] = close[:-1]
    high = np.maximum(open_, close) + np.abs(rng.normal(0, 0.3, n_bars))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 0.3, n_bars))

    index = pd.date_range("2024-01-01 00:00", periods=n_bars, freq="15min")
    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close},
        index=index,
    )
    return df
