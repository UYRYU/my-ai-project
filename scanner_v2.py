"""
レンジ通貨スキャナー v2 - K線データで「本当に往復してる」通貨を探す

v1の問題: 24hティッカーだけでは暴落/急騰後の張り付きとレンジの区別がつかない
v2の改善: K線データを取得して、実際に何回レンジを往復してるかカウント

対応取引所:
  - MEXC (現物)
  - Bybit (現物/先物)
"""

import math
import statistics
import time
import requests
from dataclasses import dataclass

TIMEOUT = 15


@dataclass
class RangeCandidate:
    exchange: str
    symbol: str
    market_type: str
    price: float
    vol_24h_pct: float
    volume_usdt: float
    # v2 追加指標
    cross_count: int        # レンジ中央を何回横切ったか (往復回数)
    range_efficiency: float # 往復効率 = cross_count / (ボラ/平均足幅)
    mean_reversion: float   # 平均回帰度 (1に近いほどレンジ)
    bb_width_pct: float     # ボリンジャーバンド幅%
    scalp_score: float      # 総合スキャルスコア


def fetch_mexc_spot_tickers() -> list[dict]:
    """MEXC現物ティッカー取得 (事前フィルタ用)"""
    try:
        resp = requests.get("https://api.mexc.com/api/v3/ticker/24hr", timeout=TIMEOUT)
        resp.raise_for_status()
        tickers = resp.json()
        results = []
        for t in tickers:
            sym = t.get("symbol", "")
            if not sym.endswith("USDT"):
                continue
            try:
                high = float(t.get("highPrice", 0))
                low = float(t.get("lowPrice", 0))
                last = float(t.get("lastPrice", 0))
                vol = float(t.get("quoteVolume", 0))
                if low <= 0 or last <= 0:
                    continue
                vol_pct = ((high - low) / low) * 100
                results.append({"symbol": sym, "price": last, "vol_pct": vol_pct, "volume": vol})
            except (ValueError, TypeError):
                continue
        return results
    except Exception as e:
        print(f"  MEXC取得エラー: {e}")
        return []


def fetch_bybit_tickers(category: str = "spot") -> list[dict]:
    """Bybitティッカー取得"""
    try:
        resp = requests.get(f"https://api.bybit.com/v5/market/tickers?category={category}", timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        tickers = data.get("result", {}).get("list", [])
        results = []
        for t in tickers:
            sym = t.get("symbol", "")
            if not sym.endswith("USDT"):
                continue
            try:
                high = float(t.get("highPrice24h", 0))
                low = float(t.get("lowPrice24h", 0))
                last = float(t.get("lastPrice", 0))
                vol = float(t.get("turnover24h", 0))
                if low <= 0 or last <= 0:
                    continue
                vol_pct = ((high - low) / low) * 100
                results.append({"symbol": sym, "price": last, "vol_pct": vol_pct, "volume": vol})
            except (ValueError, TypeError):
                continue
        return results
    except Exception as e:
        print(f"  Bybit取得エラー: {e}")
        return []


def fetch_mexc_klines(symbol: str, interval: str = "15m", limit: int = 96) -> list[dict]:
    """MEXC現物K線取得 (15分足96本=24時間)"""
    try:
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        resp = requests.get("https://api.mexc.com/api/v3/klines", params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return [{"open": float(k[1]), "high": float(k[2]), "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])} for k in data]
    except Exception:
        return []


def fetch_bybit_klines(symbol: str, category: str = "spot", interval: str = "15", limit: int = 96) -> list[dict]:
    """BybitK線取得"""
    try:
        params = {"category": category, "symbol": symbol, "interval": interval, "limit": limit}
        resp = requests.get("https://api.bybit.com/v5/market/kline", params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        klines = data.get("result", {}).get("list", [])
        # Bybitは新しい順なので逆転
        return [{"open": float(k[1]), "high": float(k[2]), "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])} for k in reversed(klines)]
    except Exception:
        return []


def analyze_range_quality(klines: list[dict]) -> dict:
    """
    K線データからレンジの質を分析

    - cross_count: 中央値を何回クロスしたか (多い=往復してる)
    - mean_reversion: 平均回帰度 (ΔPの自己相関、負なら回帰的)
    - bb_width_pct: ボリンジャーバンド幅
    """
    if len(klines) < 20:
        return {"cross_count": 0, "mean_reversion": 0, "bb_width_pct": 0, "range_efficiency": 0}

    closes = [k["close"] for k in klines]
    highs = [k["high"] for k in klines]
    lows = [k["low"] for k in klines]

    # === 1. 中央クロス回数 ===
    median_price = statistics.median(closes)
    cross_count = 0
    above = closes[0] > median_price
    for c in closes[1:]:
        now_above = c > median_price
        if now_above != above:
            cross_count += 1
            above = now_above

    # === 2. 平均回帰度 (価格変化の自己相関) ===
    # 負の自己相関 = 上がったら下がる = レンジ的
    changes = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    if len(changes) > 2 and statistics.stdev(changes) > 0:
        n = len(changes)
        mean_c = statistics.mean(changes)
        var_c = sum((c - mean_c)**2 for c in changes) / n
        if var_c > 0:
            autocorr = sum((changes[i] - mean_c) * (changes[i-1] - mean_c) for i in range(1, n)) / (n * var_c)
            # -1〜+1を0〜1にマップ (負=レンジ的=スコア高い)
            mean_reversion = max(0, min(1, (1 - autocorr) / 2))
        else:
            mean_reversion = 0.5
    else:
        mean_reversion = 0.5

    # === 3. ボリンジャーバンド幅 ===
    bb_period = min(20, len(closes))
    recent = closes[-bb_period:]
    mean = statistics.mean(recent)
    std = statistics.stdev(recent) if len(recent) > 1 else 0
    bb_width_pct = (std * 4 / mean * 100) if mean > 0 else 0  # 2σ×2の幅

    # === 4. レンジ効率 ===
    # 理想的なレンジ = クロス回数が多い + ボラがある
    # 最大クロス回数は約 len/2
    max_possible_crosses = len(closes) / 2
    range_efficiency = cross_count / max_possible_crosses if max_possible_crosses > 0 else 0

    # === 5. トレンド強度チェック ===
    # 最初の1/4の平均 vs 最後の1/4の平均
    q = len(closes) // 4
    if q > 0:
        start_avg = statistics.mean(closes[:q])
        end_avg = statistics.mean(closes[-q:])
        trend_strength = abs(end_avg - start_avg) / start_avg if start_avg > 0 else 0
    else:
        trend_strength = 0

    return {
        "cross_count": cross_count,
        "mean_reversion": mean_reversion,
        "bb_width_pct": bb_width_pct,
        "range_efficiency": range_efficiency,
        "trend_strength": trend_strength,
    }


def calc_scalp_score(vol_pct: float, volume: float, analysis: dict) -> float:
    """総合スキャルスコア計算"""
    # ボラスコア (5-30%が理想、高すぎはペナルティ)
    if vol_pct < 3:
        vol_score = vol_pct / 3
    elif vol_pct <= 30:
        vol_score = 1.0
    elif vol_pct <= 80:
        vol_score = 1.0 - (vol_pct - 30) / 100
    else:
        vol_score = 0.3  # 80%超は草コイン

    # 出来高スコア
    vol_usd_score = min(math.log10(max(volume, 1)) / 7, 1.0)

    # レンジ品質スコア
    cross = analysis["cross_count"]
    cross_score = min(cross / 15, 1.0)  # 15回以上クロスで満点

    # 平均回帰スコア
    mr_score = analysis["mean_reversion"]

    # レンジ効率
    eff_score = analysis["range_efficiency"]

    # トレンドペナルティ (トレンド強いほど減点)
    trend_penalty = max(0, 1 - analysis["trend_strength"] * 5)

    # 総合 (レンジ品質を重視)
    score = (
        vol_score * 15 +
        vol_usd_score * 10 +
        cross_score * 30 +        # クロス回数を最重視
        mr_score * 20 +
        eff_score * 15 +
        trend_penalty * 10
    )

    return round(score, 1)


def format_volume(v: float) -> str:
    if v >= 1_000_000:
        return f"{v/1_000_000:.1f}M"
    elif v >= 1_000:
        return f"{v/1_000:.0f}K"
    return f"{v:.0f}"


def run_scan(
    min_vol_pct: float = 5.0,
    min_volume: float = 500_000,
    top_n: int = 20,
    exchanges: str = "all",
):
    print("=" * 100)
    print("  レンジ通貨スキャナー v2 - K線分析で本物のレンジを検出")
    print(f"  条件: ボラ>{min_vol_pct}% / 出来高>{format_volume(min_volume)}")
    print("=" * 100)

    # Step 1: ティッカーで事前フィルタ
    print("\n[1/3] ティッカー取得中...")
    candidates = []

    if exchanges in ("all", "mexc"):
        tickers = fetch_mexc_spot_tickers()
        for t in tickers:
            if t["vol_pct"] >= min_vol_pct and t["volume"] >= min_volume:
                candidates.append({**t, "exchange": "MEXC", "type": "spot"})
        print(f"  MEXC現物: {len(tickers)}ペア中 {sum(1 for t in tickers if t['vol_pct'] >= min_vol_pct and t['volume'] >= min_volume)}ペアが条件通過")
        time.sleep(0.3)

    if exchanges in ("all", "bybit"):
        for cat, label in [("spot", "現物"), ("linear", "先物")]:
            tickers = fetch_bybit_tickers(cat)
            count = 0
            for t in tickers:
                if t["vol_pct"] >= min_vol_pct and t["volume"] >= min_volume:
                    candidates.append({**t, "exchange": "Bybit", "type": "spot" if cat == "spot" else "futures"})
                    count += 1
            print(f"  Bybit{label}: {len(tickers)}ペア中 {count}ペアが条件通過")
            time.sleep(0.3)

    print(f"\n  候補: {len(candidates)}ペア → K線分析へ")

    # Step 2: K線取得 & レンジ分析
    print(f"\n[2/3] K線分析中 (15分足×96本=24h)...")
    results = []
    total = len(candidates)

    for idx, c in enumerate(candidates):
        sym = c["symbol"]
        pct = (idx + 1) / total * 100
        print(f"\r  分析中: {idx+1}/{total} ({pct:.0f}%) {sym:20s}", end="", flush=True)

        # K線取得
        if c["exchange"] == "MEXC":
            klines = fetch_mexc_klines(sym)
        elif c["exchange"] == "Bybit":
            cat = "spot" if c["type"] == "spot" else "linear"
            klines = fetch_bybit_klines(sym, category=cat)
        else:
            continue

        if len(klines) < 20:
            continue

        # レンジ分析
        analysis = analyze_range_quality(klines)
        score = calc_scalp_score(c["vol_pct"], c["volume"], analysis)

        results.append(RangeCandidate(
            exchange=c["exchange"],
            symbol=sym.replace("USDT", "/USDT"),
            market_type=c["type"],
            price=c["price"],
            vol_24h_pct=c["vol_pct"],
            volume_usdt=c["volume"],
            cross_count=analysis["cross_count"],
            range_efficiency=analysis["range_efficiency"],
            mean_reversion=analysis["mean_reversion"],
            bb_width_pct=analysis["bb_width_pct"],
            scalp_score=score,
        ))

        # レート制限
        if (idx + 1) % 5 == 0:
            time.sleep(0.5)

    print(f"\r  分析完了: {len(results)}ペア                              ")

    # Step 3: ランキング
    results.sort(key=lambda x: x.scalp_score, reverse=True)
    top = results[:top_n]

    print(f"\n[3/3] 結果")
    print(f"\n{'='*110}")
    print(f"  レンジスキャル適性ランキング TOP{min(top_n, len(top))}")
    print(f"{'='*110}")
    print(
        f"  {'#':>2s}  {'取引所':6s} {'種別':4s} {'ペア':16s} "
        f"{'価格':>12s} {'ボラ':>7s} {'出来高':>8s} "
        f"{'往復':>4s} {'回帰度':>6s} {'効率':>5s} {'BB幅':>6s} {'スコア':>6s}"
    )
    print(f"  {'-'*104}")

    for i, r in enumerate(top, 1):
        mtype = "先物" if r.market_type == "futures" else "現物"
        mr_bar = "■" * int(r.mean_reversion * 5)
        print(
            f"  {i:2d}. {r.exchange:6s} {mtype:4s} {r.symbol:16s} "
            f"${r.price:>11.5f} {r.vol_24h_pct:>6.1f}% {format_volume(r.volume_usdt):>8s} "
            f"{r.cross_count:>4d} {r.mean_reversion:>5.2f} {r.range_efficiency:>5.2f} "
            f"{r.bb_width_pct:>5.1f}% {r.scalp_score:>6.1f}"
        )

    print(f"{'='*110}")
    print(f"\n  指標の見方:")
    print(f"    往復   = 中央値を横切った回数 (多い=レンジで往復, SPACEXは15-20回相当)")
    print(f"    回帰度 = 上がったら下がる傾向 (1.0に近いほどレンジ的)")
    print(f"    効率   = 往復回数/理論最大値 (高いほどきれいなレンジ)")
    print(f"    BB幅   = ボリンジャーバンド幅% (スキャルの利幅の目安)")
    print(f"    スコア = 全指標の重み付き総合評価")

    if top:
        print(f"\n  TOP3の詳細:")
        for i, r in enumerate(top[:3], 1):
            print(f"    {i}. {r.symbol} ({r.exchange})")
            print(f"       24hで{r.cross_count}回往復, 回帰度{r.mean_reversion:.2f}, BB幅{r.bb_width_pct:.1f}%")
            if r.cross_count >= 10 and r.mean_reversion >= 0.5:
                print(f"       → レンジ◎ スキャル向き")
            elif r.cross_count >= 5:
                print(f"       → レンジ○ 様子見推奨")
            else:
                print(f"       → レンジ△ 注意")

    return top


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    kwargs = {}

    for a in args:
        if a.startswith("--min-vol="):
            kwargs["min_vol_pct"] = float(a.split("=")[1])
        elif a.startswith("--min-volume="):
            kwargs["min_volume"] = float(a.split("=")[1])
        elif a.startswith("--top="):
            kwargs["top_n"] = int(a.split("=")[1])
        elif a.startswith("--exchange="):
            kwargs["exchanges"] = a.split("=")[1]

    run_scan(**kwargs)
