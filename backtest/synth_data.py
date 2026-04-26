"""デモ/CI 用の合成BTCライク OHLCV データ生成 (GBM + ボラクラスタ + ドリフト変化)."""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def generate(days: int = 120, tf_min: int = 5, seed: int = 42,
             start_price: float = 60_000.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = days * 24 * (60 // tf_min)
    # ボラクラスタ (GARCH風) - BTC実測 5m std ~ 0.0007 程度
    base_vol = 0.0007
    vol = np.zeros(n); vol[0] = base_vol
    for i in range(1, n):
        vol[i] = 0.93 * vol[i-1] + 0.07 * abs(rng.normal(base_vol, 0.0004))
    # トレンド切り替え (3-7日ランダム長 + やや強め, 一部ノイズ区間)
    drift = np.zeros(n)
    i = 0
    sign = 1.0
    while i < n:
        seg = int(rng.uniform(3, 7) * 24 * (60 // tf_min))
        if rng.random() < 0.25:
            d = 0.0  # ノイズ/レンジ区間
        else:
            d = sign * rng.uniform(0.00010, 0.00040)
            sign *= -1.0
        drift[i:i+seg] = d
        i += seg
    # リターン → 価格
    rets = drift + vol * rng.standard_normal(n)
    close = start_price * np.exp(np.cumsum(rets))
    # OHLC を tick からざっくり再構築 (各バー内 5 サブティック)
    sub = 5
    ohlc = np.zeros((n, 4))
    prev = start_price
    for i in range(n):
        sub_rets = vol[i] * rng.standard_normal(sub) * 0.5
        path = prev * np.exp(np.cumsum(np.r_[0.0, sub_rets]))
        # close をターゲット close に強制
        path = path * (close[i] / path[-1])
        ohlc[i] = [path[0], path.max(), path.min(), path[-1]]
        prev = path[-1]

    end = pd.Timestamp.utcnow().floor(f"{tf_min}min")
    idx = pd.date_range(end=end, periods=n, freq=f"{tf_min}min", tz="UTC")
    vol_q = (rng.lognormal(0.0, 0.5, n) * 5.0)
    df = pd.DataFrame(ohlc, index=idx, columns=["open", "high", "low", "close"])
    df["volume"] = vol_q
    df.index.name = "time"
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--tf", type=int, default=5, help="timeframe minutes")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="data/btcusdt_5m_synth.csv")
    args = ap.parse_args()

    df = generate(days=args.days, tf_min=args.tf, seed=args.seed)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out)
    print(f"Generated {len(df)} bars  range "
          f"{df['close'].min():.0f}-{df['close'].max():.0f} -> {args.out}")


if __name__ == "__main__":
    main()
