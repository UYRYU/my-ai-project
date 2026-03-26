"""
ボラティリティスキャナー - スキャルピング向き通貨を自動探索

対応取引所:
  - MEXC (現物)
  - Bybit (現物/先物)
  - Bitget (現物/先物)

評価基準:
  1. 日次ボラティリティ (高値-安値)/安値 が大きい
  2. レンジ度 (トレンドではなく往復している度合い)
  3. 出来高 (薄すぎると約定しない)
"""

import requests
import time
import statistics
from dataclasses import dataclass

TIMEOUT = 15


@dataclass
class ScanResult:
    exchange: str
    symbol: str
    price: float
    vol_24h_pct: float       # 24h (高値-安値)/安値 %
    volume_usdt: float       # 24h出来高 (USDT)
    change_24h_pct: float    # 24h変動率 %
    range_score: float       # レンジ度 (高いほどレンジ的)
    scalp_score: float       # スキャル適性スコア
    market_type: str         # "spot" or "futures"


def scan_mexc_spot() -> list[ScanResult]:
    """MEXC現物のティッカーをスキャン"""
    results = []
    try:
        url = "https://api.mexc.com/api/v3/ticker/24hr"
        resp = requests.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
        tickers = resp.json()

        for t in tickers:
            symbol = t.get("symbol", "")
            if not symbol.endswith("USDT"):
                continue

            try:
                high = float(t.get("highPrice", 0))
                low = float(t.get("lowPrice", 0))
                last = float(t.get("lastPrice", 0))
                volume = float(t.get("quoteVolume", 0))
                change = float(t.get("priceChangePercent", 0))

                if low <= 0 or last <= 0 or volume < 50000:
                    continue

                vol_pct = ((high - low) / low) * 100
                # レンジ度: ボラは大きいが方向感が少ない
                # |変動率| / ボラ が小さいほどレンジ的
                if vol_pct > 0:
                    range_score = 1 - min(abs(change) / vol_pct, 1)
                else:
                    range_score = 0

                # スキャルスコア = ボラ × レンジ度 × log(出来高)
                import math
                vol_score = min(math.log10(max(volume, 1)) / 7, 1)  # 出来高正規化
                scalp_score = vol_pct * range_score * vol_score

                results.append(ScanResult(
                    exchange="MEXC",
                    symbol=symbol.replace("USDT", "/USDT"),
                    price=last,
                    vol_24h_pct=vol_pct,
                    volume_usdt=volume,
                    change_24h_pct=change,
                    range_score=range_score,
                    scalp_score=scalp_score,
                    market_type="spot",
                ))
            except (ValueError, TypeError):
                continue

        print(f"  MEXC現物: {len(results)}ペア取得")
    except Exception as e:
        print(f"  MEXC現物エラー: {e}")
    return results


def scan_bybit_spot() -> list[ScanResult]:
    """Bybit現物のティッカーをスキャン"""
    results = []
    try:
        url = "https://api.bybit.com/v5/market/tickers?category=spot"
        resp = requests.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        tickers = data.get("result", {}).get("list", [])

        for t in tickers:
            symbol = t.get("symbol", "")
            if not symbol.endswith("USDT"):
                continue

            try:
                high = float(t.get("highPrice24h", 0))
                low = float(t.get("lowPrice24h", 0))
                last = float(t.get("lastPrice", 0))
                volume = float(t.get("turnover24h", 0))
                change = float(t.get("price24hPcnt", 0)) * 100

                if low <= 0 or last <= 0 or volume < 50000:
                    continue

                vol_pct = ((high - low) / low) * 100

                if vol_pct > 0:
                    range_score = 1 - min(abs(change) / vol_pct, 1)
                else:
                    range_score = 0

                import math
                vol_score = min(math.log10(max(volume, 1)) / 7, 1)
                scalp_score = vol_pct * range_score * vol_score

                results.append(ScanResult(
                    exchange="Bybit",
                    symbol=symbol.replace("USDT", "/USDT"),
                    price=last,
                    vol_24h_pct=vol_pct,
                    volume_usdt=volume,
                    change_24h_pct=change,
                    range_score=range_score,
                    scalp_score=scalp_score,
                    market_type="spot",
                ))
            except (ValueError, TypeError):
                continue

        print(f"  Bybit現物: {len(results)}ペア取得")
    except Exception as e:
        print(f"  Bybit現物エラー: {e}")
    return results


def scan_bybit_futures() -> list[ScanResult]:
    """Bybit先物(USDT無期限)のティッカーをスキャン"""
    results = []
    try:
        url = "https://api.bybit.com/v5/market/tickers?category=linear"
        resp = requests.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        tickers = data.get("result", {}).get("list", [])

        for t in tickers:
            symbol = t.get("symbol", "")
            if not symbol.endswith("USDT"):
                continue

            try:
                high = float(t.get("highPrice24h", 0))
                low = float(t.get("lowPrice24h", 0))
                last = float(t.get("lastPrice", 0))
                volume = float(t.get("turnover24h", 0))
                change = float(t.get("price24hPcnt", 0)) * 100

                if low <= 0 or last <= 0 or volume < 100000:
                    continue

                vol_pct = ((high - low) / low) * 100

                if vol_pct > 0:
                    range_score = 1 - min(abs(change) / vol_pct, 1)
                else:
                    range_score = 0

                import math
                vol_score = min(math.log10(max(volume, 1)) / 7, 1)
                scalp_score = vol_pct * range_score * vol_score

                results.append(ScanResult(
                    exchange="Bybit",
                    symbol=symbol.replace("USDT", "/USDT"),
                    price=last,
                    vol_24h_pct=vol_pct,
                    volume_usdt=volume,
                    change_24h_pct=change,
                    range_score=range_score,
                    scalp_score=scalp_score,
                    market_type="futures",
                ))
            except (ValueError, TypeError):
                continue

        print(f"  Bybit先物: {len(results)}ペア取得")
    except Exception as e:
        print(f"  Bybit先物エラー: {e}")
    return results


def scan_bitget_spot() -> list[ScanResult]:
    """Bitget現物のティッカーをスキャン"""
    results = []
    try:
        url = "https://api.bitget.com/api/v2/spot/market/tickers"
        resp = requests.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        tickers = data.get("data", [])

        for t in tickers:
            symbol = t.get("symbol", "")
            if not symbol.endswith("USDT"):
                continue

            try:
                high = float(t.get("high24h", 0))
                low = float(t.get("low24h", 0))
                last = float(t.get("lastPr", 0))
                volume = float(t.get("quoteVolume", 0))
                change = float(t.get("change24h", 0)) * 100

                if low <= 0 or last <= 0 or volume < 50000:
                    continue

                vol_pct = ((high - low) / low) * 100

                if vol_pct > 0:
                    range_score = 1 - min(abs(change) / vol_pct, 1)
                else:
                    range_score = 0

                import math
                vol_score = min(math.log10(max(volume, 1)) / 7, 1)
                scalp_score = vol_pct * range_score * vol_score

                results.append(ScanResult(
                    exchange="Bitget",
                    symbol=symbol.replace("USDT", "/USDT"),
                    price=last,
                    vol_24h_pct=vol_pct,
                    volume_usdt=volume,
                    change_24h_pct=change,
                    range_score=range_score,
                    scalp_score=scalp_score,
                    market_type="spot",
                ))
            except (ValueError, TypeError):
                continue

        print(f"  Bitget現物: {len(results)}ペア取得")
    except Exception as e:
        print(f"  Bitget現物エラー: {e}")
    return results


def scan_bitget_futures() -> list[ScanResult]:
    """Bitget先物(USDT無期限)のティッカーをスキャン"""
    results = []
    try:
        url = "https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES"
        resp = requests.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        tickers = data.get("data", [])

        for t in tickers:
            symbol = t.get("symbol", "")
            if not symbol.endswith("USDT"):
                continue

            try:
                high = float(t.get("high24h", 0))
                low = float(t.get("low24h", 0))
                last = float(t.get("lastPr", 0))
                volume = float(t.get("quoteVolume", 0))
                change = float(t.get("change24h", 0)) * 100

                if low <= 0 or last <= 0 or volume < 100000:
                    continue

                vol_pct = ((high - low) / low) * 100

                if vol_pct > 0:
                    range_score = 1 - min(abs(change) / vol_pct, 1)
                else:
                    range_score = 0

                import math
                vol_score = min(math.log10(max(volume, 1)) / 7, 1)
                scalp_score = vol_pct * range_score * vol_score

                results.append(ScanResult(
                    exchange="Bitget",
                    symbol=symbol.replace("USDT", "/USDT"),
                    price=last,
                    vol_24h_pct=vol_pct,
                    volume_usdt=volume,
                    change_24h_pct=change,
                    range_score=range_score,
                    scalp_score=scalp_score,
                    market_type="futures",
                ))
            except (ValueError, TypeError):
                continue

        print(f"  Bitget先物: {len(results)}ペア取得")
    except Exception as e:
        print(f"  Bitget先物エラー: {e}")
    return results


def format_volume(v: float) -> str:
    if v >= 1_000_000:
        return f"{v/1_000_000:.1f}M"
    elif v >= 1_000:
        return f"{v/1_000:.0f}K"
    return f"{v:.0f}"


def run_scan(
    min_vol_pct: float = 5.0,
    min_volume: float = 100_000,
    min_range_score: float = 0.3,
    top_n: int = 30,
    futures_only: bool = False,
    spot_only: bool = False,
):
    """全取引所をスキャンしてスキャル向き通貨をランキング"""
    print("=" * 70)
    print("  スキャルピング向き通貨スキャナー")
    print(f"  条件: ボラ>{min_vol_pct}% / 出来高>{format_volume(min_volume)} / レンジ度>{min_range_score}")
    print("=" * 70)
    print("\nスキャン中...")

    all_results = []

    if not futures_only:
        all_results.extend(scan_mexc_spot())
        time.sleep(0.3)
        all_results.extend(scan_bybit_spot())
        time.sleep(0.3)
        all_results.extend(scan_bitget_spot())
        time.sleep(0.3)

    if not spot_only:
        all_results.extend(scan_bybit_futures())
        time.sleep(0.3)
        all_results.extend(scan_bitget_futures())

    print(f"\n合計: {len(all_results)}ペア取得")

    # フィルタ
    filtered = [
        r for r in all_results
        if r.vol_24h_pct >= min_vol_pct
        and r.volume_usdt >= min_volume
        and r.range_score >= min_range_score
    ]

    # スコア順ソート
    filtered.sort(key=lambda x: x.scalp_score, reverse=True)
    top = filtered[:top_n]

    if not top:
        print("\n条件に合う通貨が見つかりませんでした。条件を緩めてみてください。")
        return []

    print(f"\n{'='*90}")
    print(f"  スキャル適性ランキング TOP{min(top_n, len(top))}")
    print(f"{'='*90}")
    print(
        f"  {'#':>2s}  {'取引所':6s} {'種別':4s} {'ペア':16s} "
        f"{'価格':>12s} {'24hボラ':>8s} {'変動率':>8s} {'出来高':>10s} "
        f"{'レンジ度':>8s} {'スコア':>7s}"
    )
    print(f"  {'-'*84}")

    for i, r in enumerate(top, 1):
        mtype = "先物" if r.market_type == "futures" else "現物"
        print(
            f"  {i:2d}. {r.exchange:6s} {mtype:4s} {r.symbol:16s} "
            f"${r.price:>11.4f} {r.vol_24h_pct:>7.1f}% {r.change_24h_pct:>+7.1f}% "
            f"{format_volume(r.volume_usdt):>10s} "
            f"{r.range_score:>7.2f} {r.scalp_score:>7.1f}"
        )

    print(f"{'='*90}")
    print("\n  スコアの見方:")
    print("    ボラ    = 24h高安値の値幅% (大きいほど値動きが大きい)")
    print("    レンジ度 = 1に近いほどレンジ的 (トレンドだと0に近い)")
    print("    スコア   = ボラ × レンジ度 × 出来高 (高いほどスキャル向き)")
    print("\n  SPACEX/USDT参考値: ボラ~7%, レンジ度~0.7-0.9")

    return top


if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    kwargs = {}

    if "--futures" in args:
        kwargs["futures_only"] = True
    if "--spot" in args:
        kwargs["spot_only"] = True

    for a in args:
        if a.startswith("--min-vol="):
            kwargs["min_vol_pct"] = float(a.split("=")[1])
        elif a.startswith("--min-volume="):
            kwargs["min_volume"] = float(a.split("=")[1])
        elif a.startswith("--min-range="):
            kwargs["min_range_score"] = float(a.split("=")[1])
        elif a.startswith("--top="):
            kwargs["top_n"] = int(a.split("=")[1])

    run_scan(**kwargs)
