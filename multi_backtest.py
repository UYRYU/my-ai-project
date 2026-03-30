"""TOP10通貨 一括バックテスト - スキャナー結果に基づく"""

import math
import random
import statistics
import time
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field

import config


# スキャナーで取得したTOP10の実データ
TOP10_COINS = [
    {"symbol": "WNX/USDT",    "exchange": "MEXC",   "type": "spot",    "price": 0.0011,  "vol_pct": 252.9, "change": -0.7,  "volume": 1_500_000, "range_score": 1.00},
    {"symbol": "ASTRAI/USDT", "exchange": "MEXC",   "type": "spot",    "price": 2.2193,  "vol_pct": 189.3, "change": -0.5,  "volume": 1_200_000, "range_score": 1.00},
    {"symbol": "CARROT/USDT", "exchange": "MEXC",   "type": "spot",    "price": 0.0020,  "vol_pct": 164.3, "change": -0.5,  "volume": 1_500_000, "range_score": 1.00},
    {"symbol": "CORE/USDT",   "exchange": "MEXC",   "type": "spot",    "price": 0.0329,  "vol_pct": 128.0, "change": -0.5,  "volume": 3_500_000, "range_score": 1.00},
    {"symbol": "CORE/USDT",   "exchange": "Bybit",  "type": "futures", "price": 0.0326,  "vol_pct": 127.9, "change": -50.3, "volume": 26_000_000,"range_score": 0.61},
    {"symbol": "CORE/USDT",   "exchange": "Bybit",  "type": "spot",    "price": 0.0328,  "vol_pct": 127.8, "change": -50.1, "volume": 6_700_000, "range_score": 0.61},
    {"symbol": "SYNA/USDT",   "exchange": "MEXC",   "type": "spot",    "price": 0.0003,  "vol_pct": 77.9,  "change": -0.2,  "volume": 1_600_000, "range_score": 1.00},
    {"symbol": "AFRD/USDT",   "exchange": "MEXC",   "type": "spot",    "price": 0.0002,  "vol_pct": 77.5,  "change": -0.3,  "volume": 1_500_000, "range_score": 1.00},
    {"symbol": "CORE/USDT",   "exchange": "Bitget", "type": "spot",    "price": 0.0328,  "vol_pct": 126.6, "change": -50.2, "volume": 1_600_000, "range_score": 0.60},
    {"symbol": "ONT/USDT",    "exchange": "MEXC",   "type": "spot",    "price": 0.0739,  "vol_pct": 68.8,  "change": 0.2,   "volume": 2_300_000, "range_score": 1.00},
]

# 比較用SPACEX
SPACEX_REF = {"symbol": "SPACEX/USDT", "exchange": "MEXC", "type": "futures", "price": 1660.0, "vol_pct": 7.0, "change": 1.8, "volume": 101_000_000, "range_score": 0.74}


@dataclass
class BacktestTrade:
    side: str
    entry_price: float
    exit_price: float
    pnl_pct: float  # %ベースPnL
    exit_reason: str


@dataclass
class CoinResult:
    symbol: str
    exchange: str
    market_type: str
    price: float
    vol_pct: float
    range_score: float
    volume: float
    # バックテスト結果
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    profit_factor: float = 0.0
    win_rate: float = 0.0
    avg_trade_pnl_pct: float = 0.0
    trades: list = field(default_factory=list)
    verdict: str = ""


def generate_coin_data(coin: dict, days: int = 1, seed: int = 42) -> list[dict]:
    """通貨の特性に基づいたシミュレーションデータ生成"""
    random.seed(seed)
    total_candles = days * 24 * 60
    klines = []

    base_price = coin["price"]
    price = base_price
    daily_vol = coin["vol_pct"] / 100  # 日次ボラ (割合)
    change_bias = coin["change"] / 100  # 方向性バイアス
    range_score = coin["range_score"]

    # 1分足あたりのボラ = 日次ボラ / sqrt(1440)
    minute_vol = daily_vol / math.sqrt(1440)

    # 平均回帰力 (レンジ度が高いほど強い)
    mean_reversion = 0.0002 + (range_score * 0.0008)

    # トレンドバイアス (1分あたり)
    trend_per_min = change_bias / 1440

    # レンジサイクル
    cycle_minutes = random.randint(60, 300)

    start_time = datetime.now(timezone.utc) - timedelta(days=days)

    for i in range(total_candles):
        candle_time = start_time + timedelta(minutes=i)
        hour = candle_time.hour

        # 時間帯ボラ変動
        if 0 <= hour < 8:
            vol_factor = 0.8
        elif 8 <= hour < 16:
            vol_factor = 1.0
        else:
            vol_factor = 1.3

        # レンジ成分
        range_amplitude = base_price * daily_vol * 0.3
        trend = math.sin(2 * math.pi * i / cycle_minutes) * range_amplitude
        trend += math.sin(2 * math.pi * i / (cycle_minutes * 2.5)) * range_amplitude * 0.5

        # ランダムウォーク
        noise = random.gauss(0, minute_vol * price * vol_factor)

        # 平均回帰
        target = base_price + trend
        reversion = (target - price) * mean_reversion

        # トレンドバイアス
        drift = price * trend_per_min

        # 急変動 (1%の確率)
        spike = 0
        if random.random() < 0.01:
            spike = random.gauss(0, price * minute_vol * 5)

        price += noise + reversion + drift + spike
        price = max(price, base_price * 0.2)  # 下限
        price = min(price, base_price * 3.0)  # 上限

        # OHLC
        open_p = price
        intra = [random.gauss(0, price * minute_vol * 0.5 * vol_factor) for _ in range(4)]
        intra_prices = [price + m for m in intra]
        high_p = max(open_p, max(intra_prices))
        low_p = min(open_p, min(intra_prices))
        close_p = price + intra[-1]
        price = close_p

        klines.append({
            "time": int(candle_time.timestamp()),
            "open": open_p, "high": high_p, "low": low_p, "close": close_p,
        })

    return klines


def run_single_backtest(coin: dict, days: int = 1, tp_pct: float = 1.0, sl_pct: float = 0.3, seed: int = 42) -> CoinResult:
    """1通貨のバックテスト"""
    klines = generate_coin_data(coin, days, seed)

    result = CoinResult(
        symbol=coin["symbol"], exchange=coin["exchange"], market_type=coin["type"],
        price=coin["price"], vol_pct=coin["vol_pct"], range_score=coin["range_score"],
        volume=coin["volume"],
    )

    bb_period = 20
    close_buffer = []
    upper = lower = 0.0
    in_position = False
    position_side = None
    entry_price = 0.0
    cooldown_until = 0

    peak_pnl = 0.0
    max_dd = 0.0
    cumulative_pnl = 0.0

    range_interval = 5  # 5分ごとにレンジ更新

    for i, candle in enumerate(klines):
        close = candle["close"]
        high = candle["high"]
        low = candle["low"]

        close_buffer.append(close)
        if len(close_buffer) > bb_period + 10:
            close_buffer = close_buffer[-(bb_period + 10):]

        # レンジ更新 (ボリンジャーバンド)
        if i % range_interval == 0 and len(close_buffer) >= bb_period:
            recent = close_buffer[-bb_period:]
            mean = statistics.mean(recent)
            std = statistics.stdev(recent) if len(recent) > 1 else 0
            upper = mean + 2.0 * std
            lower = mean - 2.0 * std

        if upper == 0 or lower == 0:
            continue

        width = upper - lower
        if width <= 0:
            continue

        if in_position:
            if position_side == "long":
                tp_price = entry_price * (1 + tp_pct / 100)
                sl_price = entry_price * (1 - sl_pct / 100)
                if high >= tp_price:
                    pnl_pct = tp_pct
                    result.trades.append(BacktestTrade("long", entry_price, tp_price, pnl_pct, "tp"))
                    result.wins += 1
                    cumulative_pnl += pnl_pct
                    in_position = False
                elif low <= sl_price:
                    pnl_pct = -sl_pct
                    result.trades.append(BacktestTrade("long", entry_price, sl_price, pnl_pct, "sl"))
                    result.losses += 1
                    cumulative_pnl += pnl_pct
                    in_position = False
                    cooldown_until = i + 60
            else:
                tp_price = entry_price * (1 - tp_pct / 100)
                sl_price = entry_price * (1 + sl_pct / 100)
                if low <= tp_price:
                    pnl_pct = tp_pct
                    result.trades.append(BacktestTrade("short", entry_price, tp_price, pnl_pct, "tp"))
                    result.wins += 1
                    cumulative_pnl += pnl_pct
                    in_position = False
                elif high >= sl_price:
                    pnl_pct = -sl_pct
                    result.trades.append(BacktestTrade("short", entry_price, sl_price, pnl_pct, "sl"))
                    result.losses += 1
                    cumulative_pnl += pnl_pct
                    in_position = False
                    cooldown_until = i + 60

            if cumulative_pnl > peak_pnl:
                peak_pnl = cumulative_pnl
            dd = peak_pnl - cumulative_pnl
            if dd > max_dd:
                max_dd = dd

        else:
            if i < cooldown_until:
                continue

            offset = width * 0.005  # エントリーオフセット

            if close <= lower + offset:
                in_position = True
                position_side = "long"
                entry_price = close
            elif close >= upper - offset:
                in_position = True
                position_side = "short"
                entry_price = close

    # 集計
    result.total_trades = result.wins + result.losses
    if result.total_trades > 0:
        result.win_rate = result.wins / result.total_trades * 100
        result.total_pnl_pct = cumulative_pnl
        result.max_drawdown_pct = max_dd
        result.avg_trade_pnl_pct = cumulative_pnl / result.total_trades

        gross_win = sum(t.pnl_pct for t in result.trades if t.pnl_pct > 0)
        gross_loss = abs(sum(t.pnl_pct for t in result.trades if t.pnl_pct <= 0))
        result.profit_factor = gross_win / gross_loss if gross_loss > 0 else float('inf')

    return result


def run_all_backtests(days: int = 1):
    """TOP10 + SPACEX全通貨のバックテスト"""
    print(f"{'='*100}")
    print(f"  TOP10通貨 スキャルピング バックテスト ({days}日間)")
    print(f"  TP={1.0}% / SL={0.3}% (3日最適パラメータ)")
    print(f"{'='*100}")

    all_coins = TOP10_COINS + [SPACEX_REF]
    results = []

    # 複数シード(乱数)で平均を取ってロバスト性を確認
    seeds = [42, 123, 456, 789, 1024]

    for coin in all_coins:
        label = f"{coin['exchange']:6s} {coin['type']:7s} {coin['symbol']:16s}"
        print(f"\n  テスト中: {label}", end="", flush=True)

        seed_results = []
        for seed in seeds:
            r = run_single_backtest(coin, days=days, tp_pct=1.0, sl_pct=0.3, seed=seed)
            seed_results.append(r)
            print(".", end="", flush=True)

        # 5シードの平均
        avg_result = CoinResult(
            symbol=coin["symbol"], exchange=coin["exchange"], market_type=coin["type"],
            price=coin["price"], vol_pct=coin["vol_pct"], range_score=coin["range_score"],
            volume=coin["volume"],
        )
        avg_result.total_trades = int(statistics.mean([r.total_trades for r in seed_results]))
        avg_result.wins = int(statistics.mean([r.wins for r in seed_results]))
        avg_result.losses = int(statistics.mean([r.losses for r in seed_results]))
        avg_result.win_rate = statistics.mean([r.win_rate for r in seed_results])
        avg_result.total_pnl_pct = statistics.mean([r.total_pnl_pct for r in seed_results])
        avg_result.max_drawdown_pct = statistics.mean([r.max_drawdown_pct for r in seed_results])
        avg_result.profit_factor = statistics.mean([r.profit_factor for r in seed_results if r.profit_factor != float('inf')])
        avg_result.avg_trade_pnl_pct = statistics.mean([r.avg_trade_pnl_pct for r in seed_results])

        # 安定性 (5シード中何回プラスか)
        positive_runs = sum(1 for r in seed_results if r.total_pnl_pct > 0)

        # 判定
        if avg_result.total_pnl_pct > 5 and avg_result.profit_factor > 1.1 and positive_runs >= 4:
            avg_result.verdict = "◎ 有望"
        elif avg_result.total_pnl_pct > 0 and avg_result.profit_factor > 1.0 and positive_runs >= 3:
            avg_result.verdict = "○ まあまあ"
        elif avg_result.total_pnl_pct > -5:
            avg_result.verdict = "△ 微妙"
        else:
            avg_result.verdict = "✗ 厳しい"

        avg_result._positive_runs = positive_runs
        avg_result._seed_pnls = [r.total_pnl_pct for r in seed_results]
        results.append(avg_result)
        print(f" → {avg_result.verdict}")

    # ソート (PnL順)
    results.sort(key=lambda x: x.total_pnl_pct, reverse=True)

    # 結果テーブル
    print(f"\n{'='*120}")
    print(f"  総合ランキング ({days}日間バックテスト, 5シード平均)")
    print(f"{'='*120}")
    print(
        f"  {'#':>2s}  {'判定':8s} {'取引所':6s} {'種別':7s} {'ペア':16s} "
        f"{'価格':>10s} {'ボラ':>7s} {'レンジ度':>8s} "
        f"{'取引数':>6s} {'勝率':>6s} {'PnL%':>8s} {'PF':>6s} {'DD%':>6s} {'安定':>4s}"
    )
    print(f"  {'-'*114}")

    for i, r in enumerate(results, 1):
        is_spacex = r.symbol == "SPACEX/USDT"
        marker = " ⬅ 参考" if is_spacex else ""
        print(
            f"  {i:2d}. {r.verdict:8s} {r.exchange:6s} {r.market_type:7s} {r.symbol:16s} "
            f"${r.price:>9.4f} {r.vol_pct:>6.1f}% {r.range_score:>7.2f} "
            f"{r.total_trades:>6d} {r.win_rate:>5.1f}% {r.total_pnl_pct:>+7.2f}% "
            f"{r.profit_factor:>5.2f} {r.max_drawdown_pct:>5.2f}% {r._positive_runs}/5{marker}"
        )

    print(f"{'='*120}")

    # 詳細分析
    print(f"\n  各通貨のシード別PnL% (安定性チェック):")
    print(f"  {'ペア':16s} {'取引所':6s} | {'Seed1':>8s} {'Seed2':>8s} {'Seed3':>8s} {'Seed4':>8s} {'Seed5':>8s} | {'平均':>8s} {'標準偏差':>8s}")
    print(f"  {'-'*95}")
    for r in results:
        pnls = r._seed_pnls
        std = statistics.stdev(pnls) if len(pnls) > 1 else 0
        avg = statistics.mean(pnls)
        pnl_str = " ".join(f"{p:>+7.2f}%" for p in pnls)
        print(f"  {r.symbol:16s} {r.exchange:6s} | {pnl_str} | {avg:>+7.2f}% {std:>7.2f}%")

    # おすすめ
    print(f"\n{'='*60}")
    print("  おすすめ:")
    for r in results:
        if "有望" in r.verdict:
            print(f"    ◎ {r.symbol} ({r.exchange} {r.market_type}) - PnL: {r.total_pnl_pct:+.2f}%, PF: {r.profit_factor:.2f}")
    for r in results:
        if "まあまあ" in r.verdict:
            print(f"    ○ {r.symbol} ({r.exchange} {r.market_type}) - PnL: {r.total_pnl_pct:+.2f}%, PF: {r.profit_factor:.2f}")

    no_good = all("有望" not in r.verdict and "まあまあ" not in r.verdict for r in results)
    if no_good:
        print("    該当なし - パラメータ調整が必要かもしれません")
    print(f"{'='*60}")

    return results


def run_param_sweep(days: int = 1):
    """各通貨でTP/SLパラメータも変えて最適解を探る"""
    print(f"\n{'='*100}")
    print(f"  通貨別 最適パラメータ探索 ({days}日間)")
    print(f"{'='*100}")

    tp_values = [0.3, 0.5, 0.8, 1.0, 1.5, 2.0]
    sl_values = [0.3, 0.5, 0.8, 1.0]

    all_coins = TOP10_COINS + [SPACEX_REF]

    print(f"\n  {'ペア':16s} {'取引所':6s} {'種別':7s} | {'最適TP':>7s} {'最適SL':>7s} {'PnL%':>8s} {'PF':>6s} {'取引数':>6s} {'勝率':>6s}")
    print(f"  {'-'*85}")

    for coin in all_coins:
        best_pnl = float('-inf')
        best_tp = best_sl = 0
        best_result = None

        for tp in tp_values:
            for sl in sl_values:
                # 3シード平均
                pnls = []
                for seed in [42, 123, 456]:
                    r = run_single_backtest(coin, days=days, tp_pct=tp, sl_pct=sl, seed=seed)
                    pnls.append(r.total_pnl_pct)

                avg_pnl = statistics.mean(pnls)
                if avg_pnl > best_pnl and r.total_trades >= 5:
                    best_pnl = avg_pnl
                    best_tp = tp
                    best_sl = sl
                    best_result = r

        if best_result:
            is_spacex = coin["symbol"] == "SPACEX/USDT"
            marker = " ⬅ 参考" if is_spacex else ""
            print(
                f"  {coin['symbol']:16s} {coin['exchange']:6s} {coin['type']:7s} | "
                f"TP={best_tp:4.1f}% SL={best_sl:4.1f}% "
                f"{best_pnl:>+7.2f}% {best_result.profit_factor:>5.2f} "
                f"{best_result.total_trades:>6d} {best_result.win_rate:>5.1f}%{marker}"
            )

    print(f"{'='*100}")


if __name__ == "__main__":
    import sys

    days = 1
    for a in sys.argv[1:]:
        if a.isdigit():
            days = int(a)

    if "--sweep" in sys.argv:
        run_param_sweep(days)
    else:
        run_all_backtests(days)

    if "--sweep" not in sys.argv:
        print("\nパラメータ最適化も実行する場合: python multi_backtest.py --sweep")
