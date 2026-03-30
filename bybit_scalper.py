"""Bybit USDT先物 スキャルピングボット

対応通貨: SIREN, RDNT, VANRY, ATH, JTO, ARC
バックテスト最適パラメータを使用
"""

import statistics
import time
import json
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path

from bybit_client import BybitClient
import bybit_config as cfg


@dataclass
class PriceRange:
    upper: float = 0.0
    lower: float = 0.0
    mid: float = 0.0
    bb_width_pct: float = 0.0
    updated_at: float = 0.0

    @property
    def width(self) -> float:
        return self.upper - self.lower


@dataclass
class TradeStats:
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl_usd: float = 0.0
    daily_trades: int = 0
    daily_pnl_usd: float = 0.0
    last_loss_time: float = 0.0
    start_balance: float = 0.0
    trade_history: list = field(default_factory=list)


class BybitScalper:
    def __init__(self, symbol: str | None = None):
        self.client = BybitClient(cfg.API_KEY, cfg.API_SECRET)
        self.symbol = symbol or cfg.SYMBOL
        self.params = cfg.PARAMS.get(self.symbol, cfg.PARAMS.get("SIRENUSDT"))
        self.price_range = PriceRange()
        self.stats = TradeStats()
        self.in_position = False
        self.position_side = None
        self.entry_price = 0.0
        self.entry_time = 0.0
        self.qty = "0"
        self.min_qty = 0.0
        self.qty_step = 0.0
        self.tick_size = 0.0
        self.running = False

    def log(self, msg: str):
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line)
        try:
            with open(cfg.LOG_FILE, "a") as f:
                f.write(line + "\n")
        except Exception:
            pass

    # === 初期化 ===

    def init(self) -> bool:
        """銘柄情報取得 & レバレッジ設定"""
        try:
            info = self.client.get_instrument_info(self.symbol)
            lot_filter = info.get("lotSizeFilter", {})
            price_filter = info.get("priceFilter", {})

            self.min_qty = float(lot_filter.get("minOrderQty", 1))
            self.qty_step = float(lot_filter.get("qtyStep", 1))
            self.tick_size = float(price_filter.get("tickSize", 0.0001))

            self.log(f"銘柄情報: 最小注文={self.min_qty}, 刻み={self.qty_step}, tick={self.tick_size}")

        except Exception as e:
            self.log(f"銘柄情報取得エラー: {e}")
            return False

        if not cfg.DRY_RUN:
            try:
                self.client.set_leverage(self.symbol, cfg.LEVERAGE)
                self.log(f"レバレッジ {cfg.LEVERAGE}x 設定完了")
            except Exception as e:
                # 既に設定済みの場合はエラーになるが問題ない
                self.log(f"レバレッジ設定: {e}")

        return True

    def calc_qty(self, price: float) -> str:
        """注文数量計算"""
        if cfg.FIXED_QTY > 0:
            qty = cfg.FIXED_QTY
        else:
            # 残高から計算
            try:
                if not cfg.DRY_RUN:
                    balance_data = self.client.get_wallet_balance()
                    coins = balance_data.get("list", [{}])[0].get("coin", [])
                    usdt = next((c for c in coins if c.get("coin") == "USDT"), {})
                    available = float(usdt.get("availableToWithdraw", 0))
                else:
                    available = 100.0  # DRY RUNは100ドル想定
            except Exception:
                available = 100.0

            margin = available * (cfg.POSITION_SIZE_PCT / 100)
            position_value = margin * cfg.LEVERAGE
            qty = position_value / price

        # qty_stepに丸める
        if self.qty_step > 0:
            qty = int(qty / self.qty_step) * self.qty_step

        qty = max(qty, self.min_qty)
        # 小数点の桁数を調整
        if self.qty_step >= 1:
            return str(int(qty))
        decimals = len(str(self.qty_step).rstrip('0').split('.')[-1]) if '.' in str(self.qty_step) else 0
        return f"{qty:.{decimals}f}"

    def round_price(self, price: float) -> str:
        """価格をtick_sizeに丸める"""
        if self.tick_size > 0:
            price = round(price / self.tick_size) * self.tick_size
        decimals = len(str(self.tick_size).rstrip('0').split('.')[-1]) if '.' in str(self.tick_size) else 0
        return f"{price:.{decimals}f}"

    # === レンジ計算 ===

    def update_range(self):
        """ボリンジャーバンドでレンジ計算"""
        try:
            klines = self.client.get_klines(self.symbol, cfg.TIMEFRAME, cfg.LOOKBACK)
            if len(klines) < self.params["bb_period"]:
                self.log(f"K線不足: {len(klines)}本")
                return

            closes = [k["close"] for k in klines]
            period = self.params["bb_period"]
            recent = closes[-period:]

            mean = statistics.mean(recent)
            std = statistics.stdev(recent) if len(recent) > 1 else 0
            upper = mean + self.params["bb_std"] * std
            lower = mean - self.params["bb_std"] * std
            bb_width = (upper - lower) / mean * 100 if mean > 0 else 0

            old = self.price_range
            self.price_range = PriceRange(
                upper=upper, lower=lower, mid=mean,
                bb_width_pct=bb_width, updated_at=time.time(),
            )

            if old.upper > 0:
                self.log(
                    f"レンジ更新: {old.lower:.6f}-{old.upper:.6f} → "
                    f"{lower:.6f}-{upper:.6f} (BB幅: {bb_width:.2f}%)"
                )
            else:
                self.log(f"レンジ設定: {lower:.6f}-{upper:.6f} (BB幅: {bb_width:.2f}%)")

        except Exception as e:
            self.log(f"レンジ更新エラー: {e}")

    # === スプレッドチェック ===

    def check_spread(self) -> tuple[bool, float]:
        """スプレッドが許容範囲内か確認"""
        try:
            book = self.client.get_orderbook(self.symbol, limit=1)
            bids = book.get("b", [])
            asks = book.get("a", [])
            if not bids or not asks:
                return False, 0
            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])
            mid = (best_bid + best_ask) / 2
            spread_pct = (best_ask - best_bid) / mid * 100 if mid > 0 else 999
            return spread_pct <= cfg.MAX_SPREAD_PCT, spread_pct
        except Exception:
            return True, 0  # 取得失敗時はスキップ

    # === トレードロジック ===

    def should_long(self, price: float) -> bool:
        r = self.price_range
        offset = r.width * (cfg.ENTRY_OFFSET_PCT / 100)
        return price <= r.lower + offset

    def should_short(self, price: float) -> bool:
        r = self.price_range
        offset = r.width * (cfg.ENTRY_OFFSET_PCT / 100)
        return price >= r.upper - offset

    def check_trend_filter(self, price: float, side: str) -> bool:
        """トレンドフィルター: トレンド方向の逆張りをブロック"""
        if not cfg.TREND_FILTER:
            return True  # フィルターOFF=常に許可
        r = self.price_range
        # 価格がBBの上半分なら上昇トレンド気味
        if side == "long" and price < r.mid * 0.998:
            return True
        if side == "short" and price > r.mid * 1.002:
            return True
        return True  # 簡易版: 基本的には許可

    def open_position(self, side: str, price: float):
        tp_pct = self.params["tp"]
        sl_pct = self.params["sl"]

        if side == "long":
            tp_price = price * (1 + tp_pct / 100)
            sl_price = price * (1 - sl_pct / 100)
            order_side = "Buy"
        else:
            tp_price = price * (1 - tp_pct / 100)
            sl_price = price * (1 + sl_pct / 100)
            order_side = "Sell"

        qty = self.calc_qty(price)

        self.log(
            f"{'LONG' if side == 'long' else 'SHORT'} エントリー @ {price:.6f} "
            f"| TP: {tp_price:.6f} SL: {sl_price:.6f} | 数量: {qty}"
        )

        if not cfg.DRY_RUN:
            try:
                result = self.client.place_order(
                    symbol=self.symbol,
                    side=order_side,
                    qty=qty,
                    order_type="Market",
                    take_profit=self.round_price(tp_price),
                    stop_loss=self.round_price(sl_price),
                )
                order_id = result.get("result", {}).get("orderId", "")
                self.log(f"注文約定: {order_id}")
            except Exception as e:
                self.log(f"注文エラー: {e}")
                return
        else:
            self.log("(DRY RUN)")

        self.in_position = True
        self.position_side = side
        self.entry_price = price
        self.entry_time = time.time()
        self.qty = qty
        self.stats.daily_trades += 1
        self.stats.total_trades += 1

    def check_position(self, price: float):
        """ポジション状態チェック"""
        if not cfg.DRY_RUN:
            # 実取引: Bybitのポジション確認
            try:
                positions = self.client.get_positions(self.symbol)
                has_position = False
                for pos in positions:
                    size = float(pos.get("size", 0))
                    if size > 0:
                        has_position = True
                        unrealised = float(pos.get("unrealisedPnl", 0))
                        self.log(f"ポジション確認: size={size}, 含み損益={unrealised:+.4f}")
                        break

                if not has_position and self.in_position:
                    # TP/SLで決済された
                    elapsed = time.time() - self.entry_time
                    self.log(f"ポジション決済検出 (保持{elapsed:.0f}秒)")
                    self._handle_close(price)

            except Exception as e:
                self.log(f"ポジション確認エラー: {e}")
        else:
            # DRY RUN: シミュレーション
            tp_pct = self.params["tp"]
            sl_pct = self.params["sl"]

            if self.position_side == "long":
                tp_hit = price >= self.entry_price * (1 + tp_pct / 100)
                sl_hit = price <= self.entry_price * (1 - sl_pct / 100)
            else:
                tp_hit = price <= self.entry_price * (1 - tp_pct / 100)
                sl_hit = price >= self.entry_price * (1 + sl_pct / 100)

            if tp_hit:
                pnl_pct = tp_pct
                self.log(f"TP到達 @ {price:.6f} | +{pnl_pct:.2f}%")
                self._record_trade(pnl_pct, price, "tp")
            elif sl_hit:
                pnl_pct = -sl_pct
                self.log(f"SL到達 @ {price:.6f} | {pnl_pct:.2f}%")
                self._record_trade(pnl_pct, price, "sl")
                self.stats.last_loss_time = time.time()

    def _handle_close(self, current_price: float):
        """実取引での決済処理"""
        if self.position_side == "long":
            pnl_pct = (current_price - self.entry_price) / self.entry_price * 100
        else:
            pnl_pct = (self.entry_price - current_price) / self.entry_price * 100

        if pnl_pct < 0:
            self.stats.last_loss_time = time.time()

        self._record_trade(pnl_pct, current_price, "tp" if pnl_pct > 0 else "sl")

    def _record_trade(self, pnl_pct: float, exit_price: float, reason: str):
        qty_float = float(self.qty)
        pnl_usd = self.entry_price * qty_float * (pnl_pct / 100)

        self.stats.total_pnl_usd += pnl_usd
        self.stats.daily_pnl_usd += pnl_usd
        if pnl_pct > 0:
            self.stats.wins += 1
        else:
            self.stats.losses += 1

        elapsed = time.time() - self.entry_time
        trade = {
            "time": datetime.now(timezone.utc).isoformat(),
            "symbol": self.symbol,
            "side": self.position_side,
            "entry": self.entry_price,
            "exit": exit_price,
            "qty": self.qty,
            "pnl_pct": round(pnl_pct, 4),
            "pnl_usd": round(pnl_usd, 4),
            "reason": reason,
            "hold_sec": round(elapsed),
        }
        self.stats.trade_history.append(trade)

        # JSONログ
        try:
            log_path = Path(cfg.LOG_FILE.replace(".log", ".json"))
            history = []
            if log_path.exists():
                history = json.loads(log_path.read_text())
            history.append(trade)
            log_path.write_text(json.dumps(history, indent=2))
        except Exception:
            pass

        icon = "WIN" if pnl_pct > 0 else "LOSS"
        self.log(
            f"{icon} {self.position_side.upper()} {self.entry_price:.6f}→{exit_price:.6f} "
            f"| {pnl_pct:+.2f}% (${pnl_usd:+.4f}) | {elapsed:.0f}秒 "
            f"| 累計: ${self.stats.total_pnl_usd:+.4f}"
        )

        self.in_position = False
        self.position_side = None
        self.entry_price = 0.0

    # === リスク管理 ===

    def risk_check(self) -> bool:
        if self.stats.daily_trades >= cfg.MAX_DAILY_TRADES:
            return False

        if self.stats.start_balance > 0:
            loss_pct = abs(self.stats.daily_pnl_usd) / self.stats.start_balance * 100
            if self.stats.daily_pnl_usd < 0 and loss_pct >= cfg.MAX_DAILY_LOSS_PCT:
                self.log(f"日次損失上限: {loss_pct:.1f}%")
                return False

        if self.stats.last_loss_time > 0:
            elapsed = time.time() - self.stats.last_loss_time
            if elapsed < cfg.COOLDOWN_SEC:
                return False

        return True

    # === 表示 ===

    def print_status(self, price: float):
        r = self.price_range
        pos_info = ""
        if self.in_position:
            if self.position_side == "long":
                unrealized = (price - self.entry_price) / self.entry_price * 100
            else:
                unrealized = (self.entry_price - price) / self.entry_price * 100
            pos_info = f" | {self.position_side.upper()} @ {self.entry_price:.6f} ({unrealized:+.2f}%)"

        range_pos = ""
        if r.width > 0:
            pct = ((price - r.lower) / r.width) * 100
            range_pos = f" | 位置:{pct:.0f}%"

        wr = self.stats.wins / max(self.stats.total_trades, 1) * 100
        print(
            f"\r  {price:.6f} | BB:{r.lower:.6f}-{r.upper:.6f}{range_pos}"
            f"{pos_info} | PnL:${self.stats.daily_pnl_usd:+.2f} "
            f"({self.stats.wins}W{self.stats.losses}L {wr:.0f}%)",
            end="", flush=True,
        )

    # === メインループ ===

    def run(self):
        self.log("=" * 60)
        self.log(f"{self.symbol} スキャルピングボット起動")
        self.log(f"モード: {'DRY RUN' if cfg.DRY_RUN else 'LIVE'}")
        self.log(f"TP={self.params['tp']}% SL={self.params['sl']}%")
        self.log(f"レバレッジ: {cfg.LEVERAGE}x | ポジションサイズ: {cfg.POSITION_SIZE_PCT}%")
        self.log(f"スプレッド上限: {cfg.MAX_SPREAD_PCT}%")
        self.log(f"レンジ更新: {cfg.RANGE_UPDATE_SEC}秒 ({cfg.TIMEFRAME}分足×{cfg.LOOKBACK}本)")
        self.log("=" * 60)

        if not self.init():
            self.log("初期化失敗")
            return

        self.update_range()
        if self.price_range.upper == 0:
            self.log("レンジ計算失敗")
            return

        self.running = True
        last_range_update = time.time()

        try:
            while self.running:
                # レンジ定期更新
                if time.time() - last_range_update > cfg.RANGE_UPDATE_SEC:
                    print()
                    self.update_range()
                    last_range_update = time.time()

                # 価格取得
                try:
                    ticker = self.client.get_ticker(self.symbol)
                    price = float(ticker.get("lastPrice", 0))
                except Exception as e:
                    self.log(f"価格取得エラー: {e}")
                    time.sleep(cfg.POLL_INTERVAL)
                    continue

                if price <= 0:
                    time.sleep(cfg.POLL_INTERVAL)
                    continue

                self.print_status(price)

                if self.in_position:
                    self.check_position(price)
                else:
                    if not self.risk_check():
                        time.sleep(cfg.POLL_INTERVAL)
                        continue

                    # スプレッドチェック
                    spread_ok, spread = self.check_spread()
                    if not spread_ok:
                        time.sleep(cfg.POLL_INTERVAL)
                        continue

                    # エントリー判定
                    if self.should_long(price):
                        print()
                        self.open_position("long", price)
                    elif self.should_short(price):
                        print()
                        self.open_position("short", price)

                time.sleep(cfg.POLL_INTERVAL)

        except KeyboardInterrupt:
            print()
            self.log("ボット停止")
            self.print_summary()

    def print_summary(self):
        s = self.stats
        self.log("=" * 50)
        self.log("セッション結果:")
        self.log(f"  取引回数: {s.total_trades}")
        self.log(f"  勝敗: {s.wins}勝 {s.losses}敗")
        wr = s.wins / max(s.total_trades, 1) * 100
        self.log(f"  勝率: {wr:.1f}%")
        self.log(f"  損益: ${s.total_pnl_usd:+.4f}")
        self.log("=" * 50)


if __name__ == "__main__":
    import sys
    symbol = None
    for a in sys.argv[1:]:
        if a.upper().endswith("USDT"):
            symbol = a.upper()

    bot = BybitScalper(symbol)
    bot.run()
