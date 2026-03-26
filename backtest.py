"""SPACEX/USDT スキャルピング バックテスト"""

import math
import random
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

from mexc_client import MexcFuturesClient
import config


@dataclass
class BacktestTrade:
    side: str
    entry_price: float
    exit_price: float
    pnl: float
    entry_time: str
    exit_time: str
    exit_reason: str  # "tp" or "sl"


@dataclass
class BacktestResult:
    trades: list[BacktestTrade] = field(default_factory=list)
    total_pnl: float = 0.0
    max_drawdown: float = 0.0
    peak_pnl: float = 0.0

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def wins(self) -> int:
        return sum(1 for t in self.trades if t.pnl > 0)

    @property
    def losses(self) -> int:
        return sum(1 for t in self.trades if t.pnl <= 0)

    @property
    def win_rate(self) -> float:
        return (self.wins / self.total_trades * 100) if self.total_trades else 0

    @property
    def avg_win(self) -> float:
        wins = [t.pnl for t in self.trades if t.pnl > 0]
        return statistics.mean(wins) if wins else 0

    @property
    def avg_loss(self) -> float:
        losses = [t.pnl for t in self.trades if t.pnl <= 0]
        return statistics.mean(losses) if losses else 0

    @property
    def profit_factor(self) -> float:
        gross_win = sum(t.pnl for t in self.trades if t.pnl > 0)
        gross_loss = abs(sum(t.pnl for t in self.trades if t.pnl <= 0))
        return gross_win / gross_loss if gross_loss > 0 else float('inf')


def fetch_backtest_data(days: int = 1) -> list[dict]:
    """MEXCからバックテスト用のK線データを取得"""
    client = MexcFuturesClient(config.API_KEY, config.API_SECRET)

    # 1分足で取得 (1日=1440本, 3日=4320本)
    # MEXCのAPIは1回最大2000本なので、必要に応じて分割取得
    all_klines = []
    total_candles = days * 24 * 60  # 1分足の本数
    interval = "Min1"

    print(f"過去{days}日分のデータを取得中...")

    # 分割取得
    batch_size = 1000
    remaining = total_candles
    end_time = None

    while remaining > 0:
        limit = min(batch_size, remaining)
        try:
            params = {"symbol": config.SYMBOL, "interval": interval, "limit": limit}
            if end_time:
                params["end"] = end_time

            import requests
            url = f"https://contract.mexc.com/api/v1/contract/kline/{config.SYMBOL}"
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            if not data.get("success") or not data.get("data"):
                print(f"  データ取得失敗、{len(all_klines)}本で続行")
                break

            klines = data["data"]
            if not klines:
                break

            all_klines = klines + all_klines  # 古い順に結合
            remaining -= len(klines)

            # 次のバッチの終了時刻を設定
            first_time = klines[0].get("time", klines[0].get("t", 0))
            end_time = int(first_time) - 1

            print(f"  取得済み: {len(all_klines)}/{total_candles}本")

            if len(klines) < limit:
                break

            time.sleep(0.5)  # レート制限対策

        except Exception as e:
            print(f"  データ取得エラー: {e}")
            break

    print(f"合計 {len(all_klines)} 本のK線データ取得完了")
    return all_klines


def generate_simulated_data(days: int = 1) -> list[dict]:
    """
    チャートの実データに基づいたシミュレーションデータ生成
    SPACEX/USDT: ベース価格1,600付近、24h高値1,668/安値1,553 (約7%レンジ)
    """
    random.seed(42)
    total_candles = days * 24 * 60
    klines = []

    base_price = 1600.0
    price = 1580.0  # 開始価格

    # チャートから読み取ったボラティリティ特性
    # 1分足で平均0.1-0.3%の値動き、時折1%近い急変動
    volatility_base = 0.0015  # 0.15% per minute
    mean_reversion = 0.0003   # 平均回帰力

    # 時間帯によるボラティリティ変動 (UTC)
    # アジア時間(0-8): やや低め、欧州(8-16): 普通、米国(16-24): 高め
    hour_vol_factor = {
        **{h: 0.8 for h in range(0, 8)},
        **{h: 1.0 for h in range(8, 16)},
        **{h: 1.3 for h in range(16, 24)},
    }

    # トレンドサイクル (数時間ごとに上下)
    trend_cycle_minutes = random.randint(120, 360)

    start_time = datetime.now(timezone.utc) - timedelta(days=days)

    for i in range(total_candles):
        candle_time = start_time + timedelta(minutes=i)
        hour = candle_time.hour
        vol_factor = hour_vol_factor.get(hour, 1.0)

        # トレンド成分 (サイン波でレンジ内を上下)
        trend = math.sin(2 * math.pi * i / trend_cycle_minutes) * 40
        # 2つ目のサイクル (長め)
        trend += math.sin(2 * math.pi * i / (trend_cycle_minutes * 2.7)) * 25

        # ランダムウォーク
        noise = random.gauss(0, volatility_base * price * vol_factor)

        # 平均回帰 (base_price付近に戻す力)
        reversion = (base_price + trend - price) * mean_reversion

        # 急変動 (1%の確率で大きな動き)
        spike = 0
        if random.random() < 0.01:
            spike = random.gauss(0, price * 0.005)

        price += noise + reversion + spike
        price = max(price, 1450)  # 下限
        price = min(price, 1750)  # 上限

        # OHLC生成
        open_p = price
        intra_moves = [random.gauss(0, price * 0.0008 * vol_factor) for _ in range(4)]
        intra_prices = [price + m for m in intra_moves]
        high_p = max(open_p, max(intra_prices))
        low_p = min(open_p, min(intra_prices))
        close_p = price + intra_moves[-1]
        price = close_p

        vol = random.uniform(500, 5000) * vol_factor

        klines.append({
            "time": int(candle_time.timestamp()),
            "open": round(open_p, 2),
            "high": round(high_p, 2),
            "low": round(low_p, 2),
            "close": round(close_p, 2),
            "vol": round(vol, 2),
        })

    # データ統計表示
    closes = [k["close"] for k in klines]
    highs = [k["high"] for k in klines]
    lows = [k["low"] for k in klines]
    print(f"シミュレーションデータ生成完了 ({len(klines)}本)")
    print(f"  期間高値: {max(highs):.1f} / 安値: {min(lows):.1f} / レンジ: {(max(highs)-min(lows))/min(lows)*100:.1f}%")
    print(f"  開始: {closes[0]:.1f} → 終了: {closes[-1]:.1f}")

    return klines


def _get_klines(days: int) -> list[dict]:
    """データ取得のヘルパー: API取得を試み、失敗時はシミュレーションデータを使用"""
    klines = fetch_backtest_data(days)
    if len(klines) < config.BOLLINGER_PERIOD + 1:
        print("APIデータ取得失敗 → シミュレーションデータで実行\n")
        klines = generate_simulated_data(days)
    return klines


def _check_trend_filter(close_buffer: list[float], side: str, period: int = 50) -> bool:
    """
    トレンドフィルター: 明確なトレンドがある場合、逆張りエントリーをスキップ
    Returns True if entry should be BLOCKED (counter-trend).

    Logic:
      - 直近20本のうち80%以上がMA上にある → 明確な上昇トレンド
        → ショート(逆張り)をブロック、ロング(順張り)は許可
      - 直近20本のうち80%以上がMA下にある → 明確な下降トレンド
        → ロング(逆張り)をブロック、ショート(順張り)は許可
      - トレンドが不明確 → 全てのエントリーを許可
    """
    if len(close_buffer) < period:
        return False

    recent = close_buffer[-period:]
    ma = statistics.mean(recent)

    # 直近の価格がMA上/下に一貫しているかチェック (80%以上片側ならトレンド)
    above_count = sum(1 for p in recent[-20:] if p > ma)
    below_count = 20 - above_count

    # 明確な上昇トレンド: ロング(順張り)はOK、ショート(逆張り)をブロック
    if above_count >= 16 and side == "short":
        return True
    # 明確な下降トレンド: ショート(順張り)はOK、ロング(逆張り)をブロック
    if below_count >= 16 and side == "long":
        return True

    return False


def _parse_candle_hour(candle_time_str: str) -> int:
    """candle_time文字列からUTC時間(hour)を抽出"""
    try:
        return int(candle_time_str.split(" ")[1].split(":")[0])
    except (IndexError, ValueError):
        return -1


def _print_equity_curve(trades: list[BacktestTrade], chart_width: int = 60, chart_height: int = 15):
    """ASCII形式のエクイティカーブを表示"""
    if not trades:
        return

    # 累計PnLの推移を計算
    cumulative = []
    running = 0.0
    for t in trades:
        running += t.pnl
        cumulative.append(running)

    if len(cumulative) < 2:
        return

    min_pnl = min(cumulative)
    max_pnl = max(cumulative)
    pnl_range = max_pnl - min_pnl

    if pnl_range == 0:
        pnl_range = 1.0  # ゼロ除算防止

    print(f"\n  エクイティカーブ (累計PnL推移):")
    print(f"  {'='*chart_width}")

    # データをチャート幅にリサンプリング
    if len(cumulative) > chart_width:
        step = len(cumulative) / chart_width
        sampled = [cumulative[int(i * step)] for i in range(chart_width)]
    else:
        sampled = cumulative

    # 各行を描画
    for row in range(chart_height, -1, -1):
        threshold = min_pnl + (pnl_range * row / chart_height)
        if row == chart_height:
            label = f"{max_pnl:+8.1f}"
        elif row == 0:
            label = f"{min_pnl:+8.1f}"
        elif row == chart_height // 2:
            mid = (max_pnl + min_pnl) / 2
            label = f"{mid:+8.1f}"
        else:
            label = "        "

        line = f"  {label} |"
        for val in sampled:
            if val >= threshold:
                line += "#"
            else:
                line += " "
        print(line)

    # X軸
    print(f"           +{'-'*len(sampled)}")
    print(f"            取引 1{' '*(len(sampled)-5)}#{len(cumulative)}")


def run_backtest(days: int = 1, verbose: bool = True, trend_filter: bool = False,
                 time_filter: tuple[int, int] | None = None,
                 range_method_override: str | None = None,
                 label: str = ""):
    """バックテストを実行

    Args:
        days: バックテスト期間(日数)
        verbose: 詳細ログ出力
        trend_filter: トレンドフィルターを有効にする
        time_filter: (start_hour, end_hour) 取引時間帯フィルター (UTC)
        range_method_override: レンジ計算方法を一時的に上書き
        label: 表示用ラベル (compare mode用)
    """
    # まずAPI取得を試み、失敗したらシミュレーションデータを使用
    klines = _get_klines(days)
    if len(klines) < config.BOLLINGER_PERIOD + 1:
        print("データが不足しています")
        return None

    # レンジ方法の一時上書き
    original_range_method = config.RANGE_METHOD
    if range_method_override:
        config.RANGE_METHOD = range_method_override

    result = BacktestResult()
    in_position = False
    position_side = None
    entry_price = 0.0
    entry_time = ""
    cooldown_until = 0
    trend_skips = 0
    time_skips = 0

    # レンジ計算用のバッファ
    close_buffer = []
    high_buffer = []
    low_buffer = []

    upper = 0.0
    lower = 0.0
    range_update_count = 0

    # レンジ更新間隔（ローソク足本数で指定、15本=15分足相当）
    range_interval = max(1, config.RANGE_UPDATE_INTERVAL // 60)

    display_label = f" [{label}]" if label else ""
    print(f"\n{'='*60}")
    print(f"バックテスト開始 (過去{days}日間){display_label}")
    print(f"データ: {len(klines)}本 (1分足)")
    print(f"設定: TP={config.TAKE_PROFIT_PCT}% SL={config.STOP_LOSS_PCT}%")
    print(f"レンジ計算: {config.RANGE_METHOD} (更新間隔: {range_interval}分)")
    print(f"注文数量: {config.ORDER_SIZE}")
    if trend_filter:
        print(f"トレンドフィルター: 有効")
    if time_filter:
        print(f"取引時間帯フィルター: {time_filter[0]:02d}:00 - {time_filter[1]:02d}:00 UTC")
    print(f"{'='*60}\n")

    for i, candle in enumerate(klines):
        close = float(candle.get("close", candle.get("c", 0)))
        high = float(candle.get("high", candle.get("h", 0)))
        low = float(candle.get("low", candle.get("l", 0)))
        ts = candle.get("time", candle.get("t", 0))

        if isinstance(ts, (int, float)):
            if ts > 1e12:
                ts = ts / 1000
            candle_time = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%m/%d %H:%M")
        else:
            candle_time = str(ts)

        close_buffer.append(close)
        high_buffer.append(high)
        low_buffer.append(low)

        # バッファ制限
        max_buf = max(config.BOLLINGER_PERIOD + 10, 60)
        if len(close_buffer) > max_buf:
            close_buffer = close_buffer[-max_buf:]
            high_buffer = high_buffer[-max_buf:]
            low_buffer = low_buffer[-max_buf:]

        # レンジ更新
        if i % range_interval == 0 and len(close_buffer) >= config.BOLLINGER_PERIOD:
            period = config.BOLLINGER_PERIOD
            recent = close_buffer[-period:]

            if config.RANGE_METHOD == "bollinger":
                mean = statistics.mean(recent)
                std = statistics.stdev(recent) if len(recent) > 1 else 0
                upper = mean + config.BOLLINGER_STD * std
                lower = mean - config.BOLLINGER_STD * std
            else:
                upper = max(high_buffer[-period:])
                lower = min(low_buffer[-period:])

            range_update_count += 1

        if upper == 0 or lower == 0:
            continue

        width = upper - lower
        if width <= 0:
            continue

        # ポジションチェック
        if in_position:
            tp, sl = _calc_tp_sl(position_side, entry_price)

            exited = False
            exit_price = 0
            exit_reason = ""

            if position_side == "long":
                if high >= tp:
                    exit_price = tp
                    exit_reason = "tp"
                    exited = True
                elif low <= sl:
                    exit_price = sl
                    exit_reason = "sl"
                    exited = True
            else:
                if low <= tp:
                    exit_price = tp
                    exit_reason = "tp"
                    exited = True
                elif high >= sl:
                    exit_price = sl
                    exit_reason = "sl"
                    exited = True

            if exited:
                if position_side == "long":
                    pnl = (exit_price - entry_price) * config.ORDER_SIZE
                else:
                    pnl = (entry_price - exit_price) * config.ORDER_SIZE

                trade = BacktestTrade(
                    side=position_side,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    pnl=pnl,
                    entry_time=entry_time,
                    exit_time=candle_time,
                    exit_reason=exit_reason,
                )
                result.trades.append(trade)
                result.total_pnl += pnl

                if result.total_pnl > result.peak_pnl:
                    result.peak_pnl = result.total_pnl
                dd = result.peak_pnl - result.total_pnl
                if dd > result.max_drawdown:
                    result.max_drawdown = dd

                if verbose:
                    icon = "+" if pnl > 0 else ""
                    mark = "WIN " if pnl > 0 else "LOSS"
                    print(
                        f"  [{candle_time}] {mark} {position_side.upper():5s} "
                        f"{entry_price:.1f} -> {exit_price:.1f} | "
                        f"PnL: {icon}{pnl:.2f} | 累計: {result.total_pnl:+.2f}"
                    )

                in_position = False
                if exit_reason == "sl":
                    cooldown_until = i + config.COOLDOWN_AFTER_LOSS // 60

        else:
            # エントリー判定
            if i < cooldown_until:
                continue

            # 時間帯フィルター
            if time_filter:
                hour = _parse_candle_hour(candle_time)
                start_h, end_h = time_filter
                if start_h <= end_h:
                    if not (start_h <= hour < end_h):
                        time_skips += 1
                        continue
                else:  # 日をまたぐ場合 (例: 22-06)
                    if not (hour >= start_h or hour < end_h):
                        time_skips += 1
                        continue

            offset = width * (config.ENTRY_OFFSET_PCT / 100)

            if close <= lower + offset:
                # トレンドフィルター
                if trend_filter and _check_trend_filter(close_buffer, "long"):
                    trend_skips += 1
                    if verbose:
                        print(f"  [{candle_time}] SKIP LONG  @ {close:.1f} (トレンドフィルター)")
                    continue

                in_position = True
                position_side = "long"
                entry_price = close
                entry_time = candle_time
                if verbose:
                    pct = ((close - lower) / width) * 100
                    print(f"  [{candle_time}] ENTRY LONG  @ {close:.1f} (レンジ{pct:.0f}%) [{lower:.1f}-{upper:.1f}]")

            elif close >= upper - offset:
                # トレンドフィルター
                if trend_filter and _check_trend_filter(close_buffer, "short"):
                    trend_skips += 1
                    if verbose:
                        print(f"  [{candle_time}] SKIP SHORT @ {close:.1f} (トレンドフィルター)")
                    continue

                in_position = True
                position_side = "short"
                entry_price = close
                entry_time = candle_time
                if verbose:
                    pct = ((close - lower) / width) * 100
                    print(f"  [{candle_time}] ENTRY SHORT @ {close:.1f} (レンジ{pct:.0f}%) [{lower:.1f}-{upper:.1f}]")

    # 未決済ポジションを最終価格で決済
    if in_position:
        last_close = float(klines[-1].get("close", klines[-1].get("c", 0)))
        if position_side == "long":
            pnl = (last_close - entry_price) * config.ORDER_SIZE
        else:
            pnl = (entry_price - last_close) * config.ORDER_SIZE
        trade = BacktestTrade(
            side=position_side, entry_price=entry_price, exit_price=last_close,
            pnl=pnl, entry_time=entry_time, exit_time="終了時", exit_reason="close"
        )
        result.trades.append(trade)
        result.total_pnl += pnl
        if verbose:
            print(f"  [終了] 未決済ポジション決済 @ {last_close:.1f} | PnL: {pnl:+.2f}")

    # フィルター統計
    if trend_filter and trend_skips > 0:
        print(f"\n  トレンドフィルター: {trend_skips}回のエントリーをスキップ")
    if time_filter and time_skips > 0:
        print(f"\n  時間帯フィルター: {time_skips}本のキャンドルをスキップ")

    # 結果表示
    _print_result(result, days)

    # エクイティカーブ表示 (verbose時のみ)
    if verbose and result.trades:
        _print_equity_curve(result.trades)

    # レンジ方法を元に戻す
    if range_method_override:
        config.RANGE_METHOD = original_range_method

    return result


def _calc_tp_sl(side: str, entry: float) -> tuple[float, float]:
    if side == "long":
        tp = entry * (1 + config.TAKE_PROFIT_PCT / 100)
        sl = entry * (1 - config.STOP_LOSS_PCT / 100)
    else:
        tp = entry * (1 - config.TAKE_PROFIT_PCT / 100)
        sl = entry * (1 + config.STOP_LOSS_PCT / 100)
    return tp, sl


def _print_result(result: BacktestResult, days: int):
    print(f"\n{'='*60}")
    print(f"  バックテスト結果 ({days}日間)")
    print(f"{'='*60}")
    print(f"  取引回数   : {result.total_trades}")
    print(f"  勝敗       : {result.wins}勝 {result.losses}敗")
    print(f"  勝率       : {result.win_rate:.1f}%")
    print(f"  損益合計   : {result.total_pnl:+.2f} USDT")
    if result.wins > 0:
        print(f"  平均利益   : {result.avg_win:+.2f} USDT")
    if result.losses > 0:
        print(f"  平均損失   : {result.avg_loss:+.2f} USDT")
    print(f"  PF         : {result.profit_factor:.2f}")
    print(f"  最大DD     : {result.max_drawdown:.2f} USDT")
    if result.total_trades > 0:
        print(f"  1取引あたり: {result.total_pnl / result.total_trades:+.2f} USDT")
    print(f"{'='*60}")

    # 時間帯別分析
    if result.trades:
        print(f"\n  時間帯別パフォーマンス:")
        hourly = {}
        for t in result.trades:
            try:
                hour = t.entry_time.split(" ")[1].split(":")[0]
                if hour not in hourly:
                    hourly[hour] = {"pnl": 0, "count": 0, "wins": 0}
                hourly[hour]["pnl"] += t.pnl
                hourly[hour]["count"] += 1
                if t.pnl > 0:
                    hourly[hour]["wins"] += 1
            except (IndexError, ValueError):
                pass

        for hour in sorted(hourly.keys()):
            h = hourly[hour]
            wr = h["wins"] / h["count"] * 100 if h["count"] else 0
            bar = "+" * int(abs(h["pnl"]) / max(abs(result.total_pnl), 1) * 20)
            sign = "+" if h["pnl"] >= 0 else "-"
            print(f"    {hour}時: {h['pnl']:+7.2f} USDT ({h['count']:2d}回, 勝率{wr:.0f}%) {sign}{bar}")

    # TP/SL設定の最適化ヒント
    if result.trades:
        tp_trades = [t for t in result.trades if t.exit_reason == "tp"]
        sl_trades = [t for t in result.trades if t.exit_reason == "sl"]
        print(f"\n  TP到達: {len(tp_trades)}回 / SL到達: {len(sl_trades)}回")
        if len(sl_trades) > len(tp_trades):
            print(f"  ヒント: SLが多い → SL幅を広げるか、エントリー位置を見直す")
        if result.win_rate > 60 and result.total_pnl < 0:
            print(f"  ヒント: 勝率は高いが損益マイナス → TP/SLの比率を見直す")


def run_compare(days: int = 1, trend_filter: bool = False,
                 time_filter: tuple[int, int] | None = None):
    """bollingerとhighlowのレンジ方法を並列実行して比較"""
    print(f"\n{'#'*60}")
    print(f"  レンジ方法比較モード (過去{days}日間)")
    print(f"  bollinger vs highlow")
    print(f"{'#'*60}")

    # データを1回だけ取得してキャッシュ (run_backtest内で取得される)
    result_boll = run_backtest(
        days, verbose=False, trend_filter=trend_filter,
        time_filter=time_filter, range_method_override="bollinger",
        label="bollinger"
    )
    result_hl = run_backtest(
        days, verbose=False, trend_filter=trend_filter,
        time_filter=time_filter, range_method_override="highlow",
        label="highlow"
    )

    # 比較表
    print(f"\n{'='*60}")
    print(f"  比較結果サマリー")
    print(f"{'='*60}")
    print(f"  {'指標':<14s} | {'bollinger':>12s} | {'highlow':>12s} | {'差分':>10s}")
    print(f"  {'-'*54}")

    metrics = []
    if result_boll and result_hl:
        metrics = [
            ("取引回数", result_boll.total_trades, result_hl.total_trades, "d"),
            ("勝率 (%)", result_boll.win_rate, result_hl.win_rate, "f"),
            ("損益合計", result_boll.total_pnl, result_hl.total_pnl, "f"),
            ("PF", result_boll.profit_factor, result_hl.profit_factor, "f"),
            ("平均利益", result_boll.avg_win, result_hl.avg_win, "f"),
            ("平均損失", result_boll.avg_loss, result_hl.avg_loss, "f"),
            ("最大DD", result_boll.max_drawdown, result_hl.max_drawdown, "f"),
        ]

        for name, v_boll, v_hl, fmt in metrics:
            diff = v_boll - v_hl
            if fmt == "d":
                print(f"  {name:<14s} | {v_boll:>12d} | {v_hl:>12d} | {diff:>+10d}")
            else:
                print(f"  {name:<14s} | {v_boll:>12.2f} | {v_hl:>12.2f} | {diff:>+10.2f}")

        # 勝者判定
        boll_pnl = result_boll.total_pnl if result_boll else 0
        hl_pnl = result_hl.total_pnl if result_hl else 0
        if boll_pnl > hl_pnl:
            winner = "bollinger"
        elif hl_pnl > boll_pnl:
            winner = "highlow"
        else:
            winner = "引き分け"
        print(f"\n  勝者: {winner} (PnL基準)")
    else:
        print("  比較に必要なデータが不足しています")

    print(f"{'='*60}")
    return result_boll, result_hl


def optimize_params(days: int = 1):
    """TP/SLパラメータを最適化"""
    print(f"パラメータ最適化中 (過去{days}日)...\n")

    tp_range = [0.3, 0.4, 0.5, 0.6, 0.8, 1.0]
    sl_range = [0.3, 0.5, 0.8, 1.0, 1.2]
    entry_range = [0.2, 0.3, 0.5]

    best_pnl = float('-inf')
    best_params = {}
    results = []

    original_tp = config.TAKE_PROFIT_PCT
    original_sl = config.STOP_LOSS_PCT
    original_entry = config.ENTRY_OFFSET_PCT

    for tp in tp_range:
        for sl in sl_range:
            for entry in entry_range:
                config.TAKE_PROFIT_PCT = tp
                config.STOP_LOSS_PCT = sl
                config.ENTRY_OFFSET_PCT = entry

                result = run_backtest(days, verbose=False)
                if result:
                    results.append({
                        "tp": tp, "sl": sl, "entry": entry,
                        "pnl": result.total_pnl, "trades": result.total_trades,
                        "win_rate": result.win_rate, "pf": result.profit_factor,
                        "dd": result.max_drawdown,
                    })
                    if result.total_pnl > best_pnl and result.total_trades >= 3:
                        best_pnl = result.total_pnl
                        best_params = {"tp": tp, "sl": sl, "entry": entry}

    # 元に戻す
    config.TAKE_PROFIT_PCT = original_tp
    config.STOP_LOSS_PCT = original_sl
    config.ENTRY_OFFSET_PCT = original_entry

    # 結果をPnL順にソート
    results.sort(key=lambda x: x["pnl"], reverse=True)

    print(f"\n{'='*75}")
    print(f"  パラメータ最適化結果 TOP10")
    print(f"{'='*75}")
    print(f"  {'TP%':>5s} {'SL%':>5s} {'Entry%':>7s} | {'PnL':>10s} {'取引':>5s} {'勝率':>6s} {'PF':>6s} {'DD':>8s}")
    print(f"  {'-'*65}")

    for r in results[:10]:
        mark = " <-- BEST" if r["tp"] == best_params.get("tp") and r["sl"] == best_params.get("sl") and r["entry"] == best_params.get("entry") else ""
        print(
            f"  {r['tp']:5.1f} {r['sl']:5.1f} {r['entry']:7.1f} | "
            f"{r['pnl']:+10.2f} {r['trades']:5d} {r['win_rate']:5.1f}% "
            f"{r['pf']:6.2f} {r['dd']:8.2f}{mark}"
        )

    if best_params:
        print(f"\n  最適パラメータ: TP={best_params['tp']}% SL={best_params['sl']}% Entry={best_params['entry']}%")
        print(f"  config.py を更新する場合:")
        print(f"    TAKE_PROFIT_PCT = {best_params['tp']}")
        print(f"    STOP_LOSS_PCT = {best_params['sl']}")
        print(f"    ENTRY_OFFSET_PCT = {best_params['entry']}")

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SPACEX/USDT スキャルピング バックテスト")
    parser.add_argument("days", nargs="?", type=int, default=1,
                        help="バックテスト期間 (日数, デフォルト: 1)")
    parser.add_argument("--optimize", action="store_true",
                        help="パラメータ最適化モード")
    parser.add_argument("--trend-filter", action="store_true",
                        help="トレンドフィルターを有効にする (逆張りエントリーをスキップ)")
    parser.add_argument("--compare", action="store_true",
                        help="bollinger と highlow のレンジ方法を比較")
    parser.add_argument("--time-filter", type=str, default=None,
                        help="取引時間帯フィルター (例: '03-12' = UTC 03:00-12:00)")

    parsed = parser.parse_args()

    # 時間帯フィルターのパース
    time_filter_val = None
    if parsed.time_filter:
        try:
            parts = parsed.time_filter.split("-")
            start_h = int(parts[0])
            end_h = int(parts[1])
            if not (0 <= start_h <= 23 and 0 <= end_h <= 23):
                print("エラー: 時間は0-23の範囲で指定してください")
                raise SystemExit(1)
            time_filter_val = (start_h, end_h)
        except (ValueError, IndexError):
            print("エラー: --time-filter は 'HH-HH' 形式で指定してください (例: '03-12')")
            raise SystemExit(1)

    if parsed.optimize:
        optimize_params(parsed.days)
    elif parsed.compare:
        run_compare(parsed.days, trend_filter=parsed.trend_filter,
                    time_filter=time_filter_val)
    else:
        run_backtest(parsed.days, verbose=True, trend_filter=parsed.trend_filter,
                     time_filter=time_filter_val)
