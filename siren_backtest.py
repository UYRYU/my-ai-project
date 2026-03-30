"""スキャナーv2 TOP候補 バックテスト & パラメータ最適化"""

import math
import random
import statistics
import time
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field

# スキャナーv2の実測データ
CANDIDATES = [
    {"symbol": "SIREN/USDT",  "exchange": "Bybit",  "type": "futures", "price": 1.70226, "vol_pct": 19.5, "bb_width": 4.4, "cross_count": 20, "mr": 0.60, "volume": 55_200_000},
    {"symbol": "SIREN/USDT",  "exchange": "MEXC",   "type": "spot",    "price": 1.70500, "vol_pct": 15.3, "bb_width": 4.6, "cross_count": 23, "mr": 0.62, "volume": 962_000},
    {"symbol": "MWXT/USDT",   "exchange": "MEXC",   "type": "spot",    "price": 0.07435, "vol_pct": 5.3,  "bb_width": 1.6, "cross_count": 31, "mr": 0.65, "volume": 601_000},
    {"symbol": "RDNT/USDT",   "exchange": "Bybit",  "type": "futures", "price": 0.00434, "vol_pct": 13.9, "bb_width": 5.7, "cross_count": 22, "mr": 0.60, "volume": 2_600_000},
    {"symbol": "ARC/USDT",    "exchange": "Bybit",  "type": "futures", "price": 0.04899, "vol_pct": 7.5,  "bb_width": 2.4, "cross_count": 21, "mr": 0.54, "volume": 3_400_000},
    {"symbol": "ATH/USDT",    "exchange": "Bybit",  "type": "futures", "price": 0.00702, "vol_pct": 6.9,  "bb_width": 1.6, "cross_count": 15, "mr": 0.65, "volume": 4_100_000},
    {"symbol": "JTO/USDT",    "exchange": "Bybit",  "type": "futures", "price": 0.28880, "vol_pct": 5.2,  "bb_width": 2.3, "cross_count": 16, "mr": 0.62, "volume": 4_200_000},
    {"symbol": "VANRY/USDT",  "exchange": "Bybit",  "type": "futures", "price": 0.00507, "vol_pct": 7.7,  "bb_width": 2.0, "cross_count": 20, "mr": 0.64, "volume": 511_000},
    {"symbol": "ENA/USDT",    "exchange": "Bybit",  "type": "spot",    "price": 0.09200, "vol_pct": 7.2,  "bb_width": 1.5, "cross_count": 15, "mr": 0.62, "volume": 4_500_000},
    {"symbol": "KAS/USDT",    "exchange": "MEXC",   "type": "spot",    "price": 0.03307, "vol_pct": 9.2,  "bb_width": 1.7, "cross_count": 16, "mr": 0.58, "volume": 2_600_000},
]


@dataclass
class Trade:
    side: str
    entry: float
    exit: float
    pnl_pct: float
    reason: str
    hold_bars: int


def generate_range_data(coin: dict, days: int, seed: int) -> list[dict]:
    """通貨の実測レンジ特性に基づいたデータ生成"""
    random.seed(seed)
    total = days * 24 * 60
    klines = []

    base = coin["price"]
    price = base
    daily_vol = coin["vol_pct"] / 100
    minute_vol = daily_vol / math.sqrt(1440)
    mr_strength = coin["mr"] * 0.001  # 平均回帰力
    cross_freq = coin["cross_count"]  # 24hクロス回数

    # クロス頻度からサイクルを逆算 (1サイクル=2クロス)
    cycle_min = max(30, 1440 / max(cross_freq / 2, 1))
    amplitude = base * (coin["bb_width"] / 100) * 0.6

    start = datetime.now(timezone.utc) - timedelta(days=days)

    for i in range(total):
        ct = start + timedelta(minutes=i)
        hour = ct.hour
        vf = 0.8 if hour < 8 else (1.3 if hour >= 16 else 1.0)

        # レンジ成分 (複数サイクル)
        wave1 = math.sin(2 * math.pi * i / cycle_min) * amplitude
        wave2 = math.sin(2 * math.pi * i / (cycle_min * 2.3)) * amplitude * 0.4
        wave3 = math.sin(2 * math.pi * i / (cycle_min * 0.6)) * amplitude * 0.25
        target = base + wave1 + wave2 + wave3

        noise = random.gauss(0, minute_vol * price * vf)
        reversion = (target - price) * mr_strength
        spike = random.gauss(0, price * minute_vol * 4) if random.random() < 0.008 else 0

        price += noise + reversion + spike
        price = max(price * 0.3, min(price, base * 2.5))

        o = price
        intra = [random.gauss(0, price * minute_vol * 0.5 * vf) for _ in range(4)]
        h = max(o, max(price + m for m in intra))
        l = min(o, min(price + m for m in intra))
        c = price + intra[-1]
        price = c

        klines.append({"time": int(ct.timestamp()), "open": o, "high": h, "low": l, "close": c})

    return klines


def backtest(klines: list, tp: float, sl: float, bb_period: int = 20, bb_std: float = 2.0,
             trend_filter: bool = False, cooldown_bars: int = 30) -> dict:
    """スキャルピングバックテスト (共通エンジン)"""
    closes = []
    trades = []
    in_pos = False
    side = None
    entry = 0.0
    entry_i = 0
    upper = lower = 0.0
    cooldown_until = 0
    cum_pnl = 0.0
    peak = 0.0
    max_dd = 0.0

    for i, k in enumerate(klines):
        c, h, l = k["close"], k["high"], k["low"]
        closes.append(c)
        if len(closes) > bb_period + 10:
            closes = closes[-(bb_period + 10):]

        if i % 5 == 0 and len(closes) >= bb_period:
            rec = closes[-bb_period:]
            m = statistics.mean(rec)
            s = statistics.stdev(rec) if len(rec) > 1 else 0
            upper = m + bb_std * s
            lower = m - bb_std * s

        if upper == 0 or lower == 0 or upper <= lower:
            continue

        if in_pos:
            if side == "long":
                tp_p = entry * (1 + tp / 100)
                sl_p = entry * (1 - sl / 100)
                if h >= tp_p:
                    pnl = tp
                    trades.append(Trade("long", entry, tp_p, pnl, "tp", i - entry_i))
                    cum_pnl += pnl; in_pos = False; cooldown_until = i + cooldown_bars
                elif l <= sl_p:
                    pnl = -sl
                    trades.append(Trade("long", entry, sl_p, pnl, "sl", i - entry_i))
                    cum_pnl += pnl; in_pos = False; cooldown_until = i + cooldown_bars
            else:
                tp_p = entry * (1 - tp / 100)
                sl_p = entry * (1 + sl / 100)
                if l <= tp_p:
                    pnl = tp
                    trades.append(Trade("short", entry, tp_p, pnl, "tp", i - entry_i))
                    cum_pnl += pnl; in_pos = False; cooldown_until = i + cooldown_bars
                elif h >= sl_p:
                    pnl = -sl
                    trades.append(Trade("short", entry, sl_p, pnl, "sl", i - entry_i))
                    cum_pnl += pnl; in_pos = False; cooldown_until = i + cooldown_bars

            if cum_pnl > peak: peak = cum_pnl
            dd = peak - cum_pnl
            if dd > max_dd: max_dd = dd
        else:
            if i < cooldown_until:
                continue

            width = upper - lower
            offset = width * 0.005

            # トレンドフィルター
            if trend_filter and len(closes) >= bb_period:
                ma = statistics.mean(closes[-bb_period:])
                short_ma = statistics.mean(closes[-5:]) if len(closes) >= 5 else ma
                trend_up = short_ma > ma * 1.002
                trend_down = short_ma < ma * 0.998
            else:
                trend_up = trend_down = False

            if c <= lower + offset and not trend_down:
                in_pos = True; side = "long"; entry = c; entry_i = i
            elif c >= upper - offset and not trend_up:
                in_pos = True; side = "short"; entry = c; entry_i = i

    # 未決済クローズ
    if in_pos:
        last = klines[-1]["close"]
        pnl = ((last - entry) / entry * 100) if side == "long" else ((entry - last) / entry * 100)
        trades.append(Trade(side, entry, last, pnl, "close", len(klines) - entry_i))
        cum_pnl += pnl

    wins = [t for t in trades if t.pnl_pct > 0]
    losses = [t for t in trades if t.pnl_pct <= 0]
    gross_win = sum(t.pnl_pct for t in wins)
    gross_loss = abs(sum(t.pnl_pct for t in losses))

    return {
        "trades": len(trades), "wins": len(wins), "losses": len(losses),
        "win_rate": len(wins) / len(trades) * 100 if trades else 0,
        "pnl_pct": cum_pnl,
        "pf": gross_win / gross_loss if gross_loss > 0 else float('inf'),
        "max_dd": max_dd,
        "avg_hold": statistics.mean([t.hold_bars for t in trades]) if trades else 0,
        "avg_win": statistics.mean([t.pnl_pct for t in wins]) if wins else 0,
        "avg_loss": statistics.mean([t.pnl_pct for t in losses]) if losses else 0,
        "trade_list": trades,
    }


def multi_seed_test(coin: dict, days: int, tp: float, sl: float,
                    trend_filter: bool = False, seeds: list = None) -> dict:
    """複数シードで平均を取る"""
    seeds = seeds or [42, 123, 456, 789, 1024]
    results = []
    for seed in seeds:
        klines = generate_range_data(coin, days, seed)
        r = backtest(klines, tp, sl, trend_filter=trend_filter)
        results.append(r)

    return {
        "pnl_pct": statistics.mean([r["pnl_pct"] for r in results]),
        "trades": int(statistics.mean([r["trades"] for r in results])),
        "win_rate": statistics.mean([r["win_rate"] for r in results]),
        "pf": statistics.mean([r["pf"] for r in results if r["pf"] != float('inf')]) if any(r["pf"] != float('inf') for r in results) else 0,
        "max_dd": statistics.mean([r["max_dd"] for r in results]),
        "avg_hold": statistics.mean([r["avg_hold"] for r in results]),
        "positive_runs": sum(1 for r in results if r["pnl_pct"] > 0),
        "seed_pnls": [r["pnl_pct"] for r in results],
        "all_results": results,
    }


def run_comparison(days: int = 1):
    """全候補の比較テスト"""
    print(f"{'='*110}")
    print(f"  レンジ通貨 スキャルピング比較テスト ({days}日間, 5シード平均)")
    print(f"  基本設定: TP=1.5% SL=0.5% + トレンドフィルターON")
    print(f"{'='*110}")

    results = []
    for coin in CANDIDATES:
        label = f"{coin['exchange']:6s} {coin['type']:7s} {coin['symbol']:14s}"
        print(f"  テスト中: {label}", end="", flush=True)
        r = multi_seed_test(coin, days, tp=1.5, sl=0.5, trend_filter=True)
        r["coin"] = coin
        results.append(r)
        mark = "◎" if r["pnl_pct"] > 5 and r["positive_runs"] >= 4 else ("○" if r["pnl_pct"] > 0 else "△")
        print(f" → {mark} PnL:{r['pnl_pct']:+.1f}% ({r['positive_runs']}/5)")

    results.sort(key=lambda x: x["pnl_pct"], reverse=True)

    print(f"\n{'='*120}")
    print(f"  ランキング")
    print(f"{'='*120}")
    print(f"  {'#':>2s}  {'取引所':6s} {'種別':7s} {'ペア':14s} {'価格':>10s} {'ボラ':>6s} {'往復':>4s} | {'取引':>4s} {'勝率':>6s} {'PnL%':>8s} {'PF':>5s} {'DD%':>6s} {'保持':>5s} {'安定':>4s}")
    print(f"  {'-'*110}")

    for i, r in enumerate(results, 1):
        c = r["coin"]
        print(
            f"  {i:2d}. {c['exchange']:6s} {c['type']:7s} {c['symbol']:14s} "
            f"${c['price']:>9.5f} {c['vol_pct']:>5.1f}% {c['cross_count']:>3d} | "
            f"{r['trades']:>4d} {r['win_rate']:>5.1f}% {r['pnl_pct']:>+7.1f}% "
            f"{r['pf']:>5.2f} {r['max_dd']:>5.2f}% {r['avg_hold']:>4.0f}m {r['positive_runs']}/5"
        )

    print(f"{'='*120}")
    return results


def optimize_siren(days: int = 1):
    """SIREN/USDT (Bybit先物) のパラメータ徹底最適化"""
    coin = CANDIDATES[0]  # SIREN/USDT Bybit futures
    print(f"\n{'='*100}")
    print(f"  SIREN/USDT (Bybit先物) パラメータ最適化 ({days}日間)")
    print(f"{'='*100}")

    tp_range = [0.5, 0.8, 1.0, 1.5, 2.0, 2.5, 3.0]
    sl_range = [0.3, 0.5, 0.8, 1.0, 1.5]
    trend_options = [False, True]

    all_results = []

    total = len(tp_range) * len(sl_range) * len(trend_options)
    count = 0

    for trend in trend_options:
        for tp in tp_range:
            for sl in sl_range:
                count += 1
                print(f"\r  最適化中: {count}/{total}", end="", flush=True)
                r = multi_seed_test(coin, days, tp, sl, trend_filter=trend, seeds=[42, 123, 456])
                all_results.append({
                    "tp": tp, "sl": sl, "trend": trend,
                    **r,
                })

    all_results.sort(key=lambda x: x["pnl_pct"], reverse=True)

    print(f"\r  最適化完了: {total}パターン tested                ")

    print(f"\n  {'='*95}")
    print(f"  TOP15 パラメータ組み合わせ")
    print(f"  {'='*95}")
    print(f"  {'#':>2s}  {'TP%':>5s} {'SL%':>5s} {'TF':>3s} | {'取引':>4s} {'勝率':>6s} {'PnL%':>8s} {'PF':>6s} {'DD%':>6s} {'安定':>4s} | {'RR比':>5s}")
    print(f"  {'-'*80}")

    for i, r in enumerate(all_results[:15], 1):
        tf = "ON" if r["trend"] else "--"
        rr = r["tp"] / r["sl"] if r["sl"] > 0 else 0
        best = " ← BEST" if i == 1 else ""
        print(
            f"  {i:2d}. TP={r['tp']:4.1f} SL={r['sl']:4.1f} {tf:>3s} | "
            f"{r['trades']:>4d} {r['win_rate']:>5.1f}% {r['pnl_pct']:>+7.2f}% "
            f"{r['pf']:>5.2f} {r['max_dd']:>5.2f}% {r['positive_runs']}/3 | "
            f"{rr:>4.1f}x{best}"
        )

    best = all_results[0]
    print(f"\n  {'='*60}")
    print(f"  最適設定:")
    print(f"    SYMBOL       = SIREN/USDT")
    print(f"    取引所        = Bybit 先物 (USDT無期限)")
    print(f"    TP           = {best['tp']}%")
    print(f"    SL           = {best['sl']}%")
    print(f"    トレンドフィルター = {'ON' if best['trend'] else 'OFF'}")
    print(f"    期待PnL      = {best['pnl_pct']:+.2f}% / {days}日")
    print(f"    PF           = {best['pf']:.2f}")
    print(f"    勝率          = {best['win_rate']:.1f}%")
    print(f"  {'='*60}")

    return best


def detailed_siren_test(days: int = 1, tp: float = None, sl: float = None, trend: bool = True):
    """SIREN最適パラメータで詳細テスト"""
    coin = CANDIDATES[0]

    if tp is None or sl is None:
        # まず最適化
        best = optimize_siren(days)
        tp = best["tp"]
        sl = best["sl"]
        trend = best["trend"]

    print(f"\n{'='*100}")
    print(f"  SIREN/USDT 詳細バックテスト ({days}日間)")
    print(f"  TP={tp}% SL={sl}% TrendFilter={'ON' if trend else 'OFF'}")
    print(f"{'='*100}\n")

    klines = generate_range_data(coin, days, seed=42)
    result = backtest(klines, tp, sl, trend_filter=trend)

    # トレード一覧
    print(f"  トレード履歴:")
    cum = 0
    for i, t in enumerate(result["trade_list"], 1):
        cum += t.pnl_pct
        icon = "WIN " if t.pnl_pct > 0 else "LOSS"
        print(f"    {i:3d}. {icon} {t.side:5s} @ {t.entry:.5f} → {t.exit:.5f} | "
              f"{t.pnl_pct:+.2f}% | 保持{t.hold_bars}分 | 累計{cum:+.2f}%")

    # サマリー
    wins = [t for t in result["trade_list"] if t.pnl_pct > 0]
    losses = [t for t in result["trade_list"] if t.pnl_pct <= 0]

    print(f"\n  {'='*50}")
    print(f"  サマリー:")
    print(f"    取引回数: {result['trades']}")
    print(f"    勝敗:     {result['wins']}勝 {result['losses']}敗 ({result['win_rate']:.1f}%)")
    print(f"    PnL:      {result['pnl_pct']:+.2f}%")
    print(f"    PF:       {result['pf']:.2f}")
    print(f"    最大DD:   {result['max_dd']:.2f}%")
    if wins:
        print(f"    平均利益:  {statistics.mean([t.pnl_pct for t in wins]):+.2f}%")
        print(f"    平均保持(勝): {statistics.mean([t.hold_bars for t in wins]):.0f}分")
    if losses:
        print(f"    平均損失:  {statistics.mean([t.pnl_pct for t in losses]):+.2f}%")
        print(f"    平均保持(敗): {statistics.mean([t.hold_bars for t in losses]):.0f}分")

    # 時間帯別
    hourly = {}
    start = datetime.now(timezone.utc) - timedelta(days=days)
    for t in result["trade_list"]:
        # entry_iからおおよその時間を逆算
        pass  # 簡略化

    # 100ドル運用シミュレーション
    print(f"\n  {'='*50}")
    print(f"  100ドル運用シミュレーション:")
    leverages = [1, 3, 5, 10]
    for lev in leverages:
        # 各トレードの実損益
        balance = 100.0
        min_balance = 100.0
        for t in result["trade_list"]:
            pnl_usd = balance * (t.pnl_pct / 100) * lev
            balance += pnl_usd
            if balance < min_balance:
                min_balance = balance
            if balance <= 0:
                balance = 0
                break
        max_dd_usd = 100 - min_balance
        print(f"    {lev:2d}x: ${balance:>8.2f} (損益: ${balance-100:>+7.2f}) 最低残高: ${min_balance:.2f}")

    print(f"  {'='*50}")

    return result


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]

    days = 1
    for a in args:
        if a.isdigit():
            days = int(a)

    if "--compare" in args:
        run_comparison(days)
    elif "--optimize" in args:
        optimize_siren(days)
    elif "--detail" in args:
        detailed_siren_test(days)
    else:
        # デフォルト: 全部やる
        print("\n" + "=" * 50)
        print("  STEP 1: 全候補比較")
        print("=" * 50)
        run_comparison(days)

        print("\n" + "=" * 50)
        print("  STEP 2: SIREN/USDT 最適化 + 詳細テスト")
        print("=" * 50)
        detailed_siren_test(days)
