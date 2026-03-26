"""SPACEX/USDT スキャルピングボット"""

import time
import statistics
from datetime import datetime, timezone
from dataclasses import dataclass, field

from mexc_client import MexcFuturesClient
import config


@dataclass
class PriceRange:
    upper: float
    lower: float
    mid: float
    updated_at: float = 0.0

    @property
    def width(self) -> float:
        return self.upper - self.lower

    @property
    def width_pct(self) -> float:
        return (self.width / self.mid) * 100 if self.mid else 0


@dataclass
class TradeStats:
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    daily_trades: int = 0
    daily_pnl: float = 0.0
    last_trade_time: float = 0.0
    last_loss_time: float = 0.0


class SpacexScalper:
    def __init__(self):
        self.client = MexcFuturesClient(config.API_KEY, config.API_SECRET)
        self.price_range = PriceRange(upper=0, lower=0, mid=0)
        self.stats = TradeStats()
        self.in_position = False
        self.position_side = None  # "long" or "short"
        self.entry_price = 0.0
        self.running = False

    def log(self, msg: str):
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(f"[{ts}] {msg}")

    # === レンジ計算 ===

    def calculate_range_bollinger(self, closes: list[float]) -> PriceRange:
        """ボリンジャーバンドでレンジ計算"""
        period = min(config.BOLLINGER_PERIOD, len(closes))
        recent = closes[-period:]
        mean = statistics.mean(recent)
        std = statistics.stdev(recent) if len(recent) > 1 else 0
        upper = mean + config.BOLLINGER_STD * std
        lower = mean - config.BOLLINGER_STD * std
        return PriceRange(upper=upper, lower=lower, mid=mean, updated_at=time.time())

    def calculate_range_highlow(self, highs: list[float], lows: list[float]) -> PriceRange:
        """直近高値安値でレンジ計算"""
        period = min(config.LOOKBACK_PERIODS, len(highs))
        upper = max(highs[-period:])
        lower = min(lows[-period:])
        mid = (upper + lower) / 2
        return PriceRange(upper=upper, lower=lower, mid=mid, updated_at=time.time())

    def update_range(self):
        """レンジを再計算して更新"""
        try:
            klines = self.client.get_klines(
                config.SYMBOL, config.TIMEFRAME, config.LOOKBACK_PERIODS + 5
            )
            if not klines:
                self.log("⚠ K線データなし")
                return

            closes = [float(k.get("close", k.get("c", 0))) for k in klines]
            highs = [float(k.get("high", k.get("h", 0))) for k in klines]
            lows = [float(k.get("low", k.get("l", 0))) for k in klines]

            if config.RANGE_METHOD == "bollinger":
                new_range = self.calculate_range_bollinger(closes)
            else:
                new_range = self.calculate_range_highlow(highs, lows)

            old = self.price_range
            self.price_range = new_range

            if old.upper > 0:
                self.log(
                    f"レンジ更新: {old.lower:.1f}-{old.upper:.1f} → "
                    f"{new_range.lower:.1f}-{new_range.upper:.1f} "
                    f"(幅: {new_range.width_pct:.2f}%)"
                )
            else:
                self.log(
                    f"レンジ設定: {new_range.lower:.1f}-{new_range.upper:.1f} "
                    f"(幅: {new_range.width_pct:.2f}%)"
                )

        except Exception as e:
            self.log(f"レンジ更新エラー: {e}")

    # === トレードロジック ===

    def should_long(self, price: float) -> bool:
        """ロングエントリー条件"""
        offset = self.price_range.width * (config.ENTRY_OFFSET_PCT / 100)
        entry_zone = self.price_range.lower + offset
        return price <= entry_zone

    def should_short(self, price: float) -> bool:
        """ショートエントリー条件"""
        offset = self.price_range.width * (config.ENTRY_OFFSET_PCT / 100)
        entry_zone = self.price_range.upper - offset
        return price >= entry_zone

    def calc_tp_sl(self, side: str, entry: float) -> tuple[float, float]:
        """TP/SL価格を計算"""
        if side == "long":
            tp = entry * (1 + config.TAKE_PROFIT_PCT / 100)
            sl = entry * (1 - config.STOP_LOSS_PCT / 100)
        else:
            tp = entry * (1 - config.TAKE_PROFIT_PCT / 100)
            sl = entry * (1 + config.STOP_LOSS_PCT / 100)
        return round(tp, 2), round(sl, 2)

    def open_position(self, side: str, price: float):
        """ポジションオープン"""
        tp, sl = self.calc_tp_sl(side, price)
        open_type = 2 if config.MARGIN_MODE == "cross" else 1

        if side == "long":
            order_side = 1  # 買い(ロングオープン)
        else:
            order_side = 3  # 売り(ショートオープン)

        self.log(
            f"{'🟢 LONG' if side == 'long' else '🔴 SHORT'} @ {price:.2f} "
            f"| TP: {tp:.2f} SL: {sl:.2f} | 数量: {config.ORDER_SIZE}"
        )

        if not config.DRY_RUN:
            try:
                result = self.client.place_order(
                    symbol=config.SYMBOL,
                    side=order_side,
                    vol=config.ORDER_SIZE,
                    order_type=5,  # 成行
                    open_type=open_type,
                    take_profit_price=tp,
                    stop_loss_price=sl,
                )
                self.log(f"注文結果: {result}")
            except Exception as e:
                self.log(f"注文エラー: {e}")
                return
        else:
            self.log("(DRY RUN - 実注文なし)")

        self.in_position = True
        self.position_side = side
        self.entry_price = price
        self.stats.daily_trades += 1
        self.stats.total_trades += 1

    def check_position_exit(self, price: float):
        """ポジション決済チェック (DRY RUNモード用)"""
        if not config.DRY_RUN:
            # 実取引ではTP/SLが注文に含まれるので、ポジション確認で判定
            try:
                positions = self.client.get_positions(config.SYMBOL)
                data = positions.get("data", [])
                if not data:
                    self.log("ポジション決済済み")
                    self.in_position = False
                    self.position_side = None
            except Exception as e:
                self.log(f"ポジション確認エラー: {e}")
            return

        # DRY RUNモードでのシミュレーション
        tp, sl = self.calc_tp_sl(self.position_side, self.entry_price)

        if self.position_side == "long":
            if price >= tp:
                pnl = (tp - self.entry_price) * config.ORDER_SIZE
                self.log(f"✅ LONG利確 @ {price:.2f} | PnL: +{pnl:.2f} USDT")
                self._record_trade(pnl)
            elif price <= sl:
                pnl = (sl - self.entry_price) * config.ORDER_SIZE
                self.log(f"❌ LONG損切り @ {price:.2f} | PnL: {pnl:.2f} USDT")
                self._record_trade(pnl)
                self.stats.last_loss_time = time.time()
        else:  # short
            if price <= tp:
                pnl = (self.entry_price - tp) * config.ORDER_SIZE
                self.log(f"✅ SHORT利確 @ {price:.2f} | PnL: +{pnl:.2f} USDT")
                self._record_trade(pnl)
            elif price >= sl:
                pnl = (self.entry_price - sl) * config.ORDER_SIZE
                self.log(f"❌ SHORT損切り @ {price:.2f} | PnL: {pnl:.2f} USDT")
                self._record_trade(pnl)
                self.stats.last_loss_time = time.time()

    def _record_trade(self, pnl: float):
        self.stats.total_pnl += pnl
        self.stats.daily_pnl += pnl
        if pnl > 0:
            self.stats.wins += 1
        else:
            self.stats.losses += 1
        self.in_position = False
        self.position_side = None
        self.entry_price = 0.0
        self.stats.last_trade_time = time.time()

    # === リスク管理 ===

    def risk_check(self) -> bool:
        """取引可能かチェック"""
        if self.stats.daily_trades >= config.MAX_DAILY_TRADES:
            self.log("⛔ 1日の取引上限に達しました")
            return False

        if self.stats.daily_pnl <= -config.MAX_DAILY_LOSS_USDT:
            self.log(f"⛔ 1日の損失上限に達しました ({self.stats.daily_pnl:.2f} USDT)")
            return False

        if self.stats.last_loss_time > 0:
            elapsed = time.time() - self.stats.last_loss_time
            if elapsed < config.COOLDOWN_AFTER_LOSS:
                remaining = config.COOLDOWN_AFTER_LOSS - elapsed
                self.log(f"⏳ クールダウン中 (残り{remaining:.0f}秒)")
                return False

        return True

    # === メインループ ===

    def print_status(self, price: float):
        r = self.price_range
        pos = ""
        if self.in_position:
            unrealized = 0
            if self.position_side == "long":
                unrealized = (price - self.entry_price) * config.ORDER_SIZE
            else:
                unrealized = (self.entry_price - price) * config.ORDER_SIZE
            pos = f" | ポジ: {self.position_side.upper()} @ {self.entry_price:.2f} (含み損益: {unrealized:+.2f})"

        position_in_range = ""
        if r.width > 0:
            pct_from_bottom = ((price - r.lower) / r.width) * 100
            position_in_range = f" | レンジ位置: {pct_from_bottom:.0f}%"

        print(
            f"\r  価格: {price:.2f} | "
            f"レンジ: {r.lower:.1f}-{r.upper:.1f}"
            f"{position_in_range}{pos} | "
            f"損益: {self.stats.daily_pnl:+.2f} ({self.stats.daily_trades}回)",
            end="", flush=True,
        )

    def run(self):
        self.log("=" * 60)
        self.log(f"SPACEX/USDT スキャルピングボット起動")
        self.log(f"モード: {'DRY RUN (デモ)' if config.DRY_RUN else '🔴 LIVE取引'}")
        self.log(f"レンジ計算: {config.RANGE_METHOD} ({config.TIMEFRAME})")
        self.log(f"注文数量: {config.ORDER_SIZE} | レバレッジ: {config.LEVERAGE}x")
        self.log(f"利確: {config.TAKE_PROFIT_PCT}% | 損切り: {config.STOP_LOSS_PCT}%")
        self.log(f"レンジ更新間隔: {config.RANGE_UPDATE_INTERVAL}秒")
        self.log("=" * 60)

        # レバレッジ設定
        if not config.DRY_RUN:
            try:
                self.client.set_leverage(config.SYMBOL, config.LEVERAGE)
                self.log(f"レバレッジ {config.LEVERAGE}x 設定完了")
            except Exception as e:
                self.log(f"レバレッジ設定エラー: {e}")

        # 初回レンジ計算
        self.update_range()
        if self.price_range.upper == 0:
            self.log("レンジ計算失敗。終了します。")
            return

        self.running = True
        last_range_update = time.time()

        try:
            while self.running:
                # レンジ定期更新
                if time.time() - last_range_update > config.RANGE_UPDATE_INTERVAL:
                    print()  # 改行
                    self.update_range()
                    last_range_update = time.time()

                # 現在価格取得
                try:
                    ticker = self.client.get_ticker(config.SYMBOL)
                    price = float(ticker.get("lastPrice", ticker.get("last", 0)))
                except Exception as e:
                    self.log(f"価格取得エラー: {e}")
                    time.sleep(config.POLL_INTERVAL)
                    continue

                if price <= 0:
                    time.sleep(config.POLL_INTERVAL)
                    continue

                # ステータス表示
                self.print_status(price)

                # ポジションチェック
                if self.in_position:
                    self.check_position_exit(price)
                else:
                    # リスクチェック
                    if not self.risk_check():
                        time.sleep(config.POLL_INTERVAL)
                        continue

                    # エントリー判定
                    if self.should_long(price):
                        print()
                        self.open_position("long", price)
                    elif self.should_short(price):
                        print()
                        self.open_position("short", price)

                time.sleep(config.POLL_INTERVAL)

        except KeyboardInterrupt:
            print()
            self.log("ボット停止")
            self.print_summary()

    def print_summary(self):
        s = self.stats
        self.log("=" * 40)
        self.log("セッション結果:")
        self.log(f"  取引回数: {s.total_trades}")
        self.log(f"  勝敗: {s.wins}勝 {s.losses}敗")
        winrate = (s.wins / max(s.total_trades, 1)) * 100
        self.log(f"  勝率: {winrate:.1f}%")
        self.log(f"  損益合計: {s.total_pnl:+.2f} USDT")
        self.log("=" * 40)


if __name__ == "__main__":
    bot = SpacexScalper()
    bot.run()
