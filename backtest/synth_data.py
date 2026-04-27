"""デモ/CI 用の合成 暗号通貨ライク OHLCV データ生成 (GBM + ボラクラスタ + ドリフト変化)."""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


# シンボル別プリセット (start_price, vol_mult, drift_mult, seed_base)
# vol_mult/drift_mult は BTC 基準 (= 1.0) からの倍率.
SYMBOL_PRESETS: dict[str, dict] = {
    "BTCUSDT":  dict(start=60_000.0, vol_mult=1.0,  drift_mult=1.0,  seed=42),
    "ETHUSDT":  dict(start=3_000.0,  vol_mult=1.3,  drift_mult=1.2,  seed=43),
    "DOGEUSDT": dict(start=0.10,     vol_mult=2.5,  drift_mult=1.4,  seed=44),
    "XRPUSDT":  dict(start=0.50,     vol_mult=2.0,  drift_mult=1.3,  seed=45),
    "SOLUSDT":  dict(start=140.0,    vol_mult=1.6,  drift_mult=1.3,  seed=46),
}


def generate(days: int = 120, tf_min: int = 5, seed: int = 42,
             start_price: float = 60_000.0,
             vol_mult: float = 1.0, drift_mult: float = 1.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = days * 24 * (60 // tf_min)
    # ボラ/ドリフトを TF にスケール (sqrt-time / linear-time)
    tf_scale = (tf_min / 5.0) ** 0.5      # M5 基準で sqrt スケール
    drift_scale = (tf_min / 5.0) * drift_mult  # ドリフトは線形 + シンボル倍率
    base_vol = 0.0007 * tf_scale * vol_mult
    vol = np.zeros(n); vol[0] = base_vol
    for i in range(1, n):
        vol[i] = 0.93 * vol[i-1] + 0.07 * abs(rng.normal(base_vol, 0.0004 * tf_scale * vol_mult))
    # トレンド切り替え (3-7日ランダム長 + やや強め, 一部ノイズ区間)
    drift = np.zeros(n)
    i = 0
    sign = 1.0
    while i < n:
        seg = int(rng.uniform(3, 7) * 24 * (60 // tf_min))
        if rng.random() < 0.25:
            d = 0.0  # ノイズ/レンジ区間
        else:
            d = sign * rng.uniform(0.00010, 0.00040) * drift_scale
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
    ap.add_argument("--seed", type=int, default=None,
                    help="override symbol preset seed")
    ap.add_argument("--symbol", default="BTCUSDT",
                    help=f"preset symbol: {list(SYMBOL_PRESETS.keys())}")
    ap.add_argument("--start", type=float, default=None,
                    help="override start price")
    ap.add_argument("--vol-mult", type=float, default=None,
                    help="override volatility multiplier vs BTC")
    ap.add_argument("--drift-mult", type=float, default=None,
                    help="override drift multiplier vs BTC")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    preset = SYMBOL_PRESETS.get(args.symbol, SYMBOL_PRESETS["BTCUSDT"])
    seed = args.seed if args.seed is not None else preset["seed"]
    start = args.start if args.start is not None else preset["start"]
    vol_mult = args.vol_mult if args.vol_mult is not None else preset["vol_mult"]
    drift_mult = args.drift_mult if args.drift_mult is not None else preset["drift_mult"]
    out = args.out or f"data/{args.symbol.lower()}_{args.tf}m_synth.csv"

    df = generate(days=args.days, tf_min=args.tf, seed=seed,
                  start_price=start, vol_mult=vol_mult, drift_mult=drift_mult)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out)
    fmt = ".6f" if start < 1.0 else ".2f" if start < 100 else ".0f"
    print(f"[{args.symbol}] Generated {len(df)} bars  "
          f"range {df['close'].min():{fmt}}-{df['close'].max():{fmt}}  -> {out}")


if __name__ == "__main__":
    main()
