"""Bybit マルチ通貨 アダプティブスキャルパー

レンジ相場 → 逆張り (BBバウンス)
トレンド相場 → 順張り (BBブレイクアウト)
自動判定で切り替え + 5通貨同時対応
"""

import statistics
import time
import json
import threading
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path

from bybit_client import BybitClient
import bybit_config as cfg


# === 通貨別最適パラメータ ===
COIN_PARAMS = {
    "SIRENUSDT": {"tp_range": 1.5, "sl_range": 0.3, "tp_trend": 2.0, "sl_trend": 0.5},
    "RDNTUSDT":  {"tp_range": 2.5, "sl_range": 1.0, "tp_trend": 2.5, "sl_trend": 0.8},
    "VANRYUSDT": {"tp_range": 1.5, "sl_range": 0.8, "tp_trend": 2.0, "sl_trend": 0.5},
    "ATHUSDT":   {"tp_range": 1.5, "sl_range": 1.0, "tp_trend": 2.0, "sl_trend": 0.8},
    "JTOUSDT":   {"tp_range": 0.5, "sl_range": 0.5, "tp_trend": 1.5, "sl_trend": 0.5},
    "ARCUSDT":   {"tp_range": 1.0, "sl_range": 0.8, "tp_trend": 2.0, "sl_trend": 0.5},
}


@dataclass
class CoinState:
    symbol: str
    mode: str = "unknown"      # "range" or "trend_up" or "trend_down"
    upper: float = 0.0
    lower: float = 0.0
    mid: float = 0.0
    bb_width_pct: float = 0.0
    adx: float = 0.0           # トレンド強度
    trend_score: float = 0.0   # -1(下降)〜0(レンジ)〜+1(上昇)
    in_position: bool = False
    position_side: str = ""
    entry_price: float = 0.0
    entry_time: float = 0.0
    qty: str = "0"
    wins: int = 0
    losses: int = 0
    pnl_usd: float = 0.0
    pnl_usd_fixed: float = 0.0   # 比較用：固定ベットだった場合のPnL
    last_loss_time: float = 0.0
    daily_trades: int = 0
    min_qty: float = 1.0
    qty_step: float = 1.0
    tick_size: float = 0.0001
    bet_multiplier: float = 1.0   # プログレッシブベット倍率
    trade_history: list = field(default_factory=list)


def log(symbol: str, msg: str):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    line = f"[{ts}] [{symbol:10s}] {msg}"
    print(line)
    try:
        with open("multi_trades.log", "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def calc_trend_score(closes: list[float], period: int = 20) -> tuple[float, str]:
    """
    トレンド/レンジ判定

    returns: (trend_score, mode)
      trend_score: -1〜+1 (0に近いほどレンジ)
      mode: "range", "trend_up", "trend_down"
    """
    if len(closes) < period:
        return 0.0, "range"

    recent = closes[-period:]
    mean = statistics.mean(recent)
    std = statistics.stdev(recent) if len(recent) > 1 else 0

    # 1. 方向性: 前半と後半の平均の差
    half = period // 2
    first_half = statistics.mean(recent[:half])
    second_half = statistics.mean(recent[half:])
    direction = (second_half - first_half) / mean if mean > 0 else 0

    # 2. 一貫性: 連続して同方向に動いてるか
    changes = [recent[i] - recent[i-1] for i in range(1, len(recent))]
    pos_changes = sum(1 for c in changes if c > 0)
    consistency = abs(pos_changes / len(changes) - 0.5) * 2  # 0=ランダム, 1=一方向

    # 3. 価格位置: BBの上半分か下半分か
    if std > 0:
        z_score = (closes[-1] - mean) / std
    else:
        z_score = 0

    # スコア統合
    trend_score = direction * 50 * (1 + consistency)
    trend_score = max(-1, min(1, trend_score))

    # 閾値で判定
    if abs(trend_score) > 0.3:
        mode = "trend_up" if trend_score > 0 else "trend_down"
    else:
        mode = "range"

    return trend_score, mode


def calc_bb(closes: list[float], period: int = 20, std_mult: float = 2.0) -> tuple[float, float, float]:
    """ボリンジャーバンド計算"""
    recent = closes[-period:]
    mean = statistics.mean(recent)
    std = statistics.stdev(recent) if len(recent) > 1 else 0
    upper = mean + std_mult * std
    lower = mean - std_mult * std
    return upper, lower, mean


def round_price(price: float, tick_size: float) -> str:
    if tick_size > 0:
        price = round(price / tick_size) * tick_size
    decimals = len(str(tick_size).rstrip('0').split('.')[-1]) if '.' in str(tick_size) else 0
    return f"{price:.{decimals}f}"


def calc_qty(price: float, available: float, state: CoinState, use_multiplier: bool = True) -> str:
    if cfg.FIXED_QTY > 0:
        qty = cfg.FIXED_QTY
    else:
        # 5通貨分散なのでPOSITION_SIZE_PCTを通貨数で割る
        per_coin_pct = cfg.POSITION_SIZE_PCT / max(len(SYMBOLS), 1)
        margin = available * (per_coin_pct / 100)
        position_value = margin * cfg.LEVERAGE
        qty = position_value / price

    # プログレッシブベット: 倍率を適用
    if use_multiplier:
        qty *= state.bet_multiplier

    if state.qty_step > 0:
        qty = int(qty / state.qty_step) * state.qty_step
    qty = max(qty, state.min_qty)

    if state.qty_step >= 1:
        return str(int(qty))
    decimals = len(str(state.qty_step).rstrip('0').split('.')[-1]) if '.' in str(state.qty_step) else 0
    return f"{qty:.{decimals}f}"


# === 取引対象通貨 ===
SYMBOLS = getattr(cfg, 'SYMBOLS', [cfg.SYMBOL])
if isinstance(SYMBOLS, str):
    SYMBOLS = [SYMBOLS]


class MultiScalper:
    def __init__(self):
        self.client = BybitClient(cfg.API_KEY, cfg.API_SECRET)
        self.states: dict[str, CoinState] = {}
        self.available_balance = 100.0
        self.running = False
        self.lock = threading.Lock()

    def init_coin(self, symbol: str) -> bool:
        try:
            info = self.client.get_instrument_info(symbol)
            lot = info.get("lotSizeFilter", {})
            pf = info.get("priceFilter", {})

            state = CoinState(symbol=symbol)
            state.min_qty = float(lot.get("minOrderQty", 1))
            state.qty_step = float(lot.get("qtyStep", 1))
            state.tick_size = float(pf.get("tickSize", 0.0001))

            self.states[symbol] = state
            log(symbol, f"初期化OK: 最小={state.min_qty}, 刻み={state.qty_step}")
            return True
        except Exception as e:
            log(symbol, f"初期化エラー: {e}")
            return False

    def update_range(self, symbol: str):
        state = self.states[symbol]
        try:
            klines = self.client.get_klines(symbol, cfg.TIMEFRAME, cfg.LOOKBACK)
            if len(klines) < 20:
                return

            closes = [k["close"] for k in klines]
            bb_period = COIN_PARAMS.get(symbol, {}).get("bb_period", 20)
            bb_std = COIN_PARAMS.get(symbol, {}).get("bb_std", 2.0)

            upper, lower, mid = calc_bb(closes, bb_period, bb_std)
            trend_score, mode = calc_trend_score(closes, bb_period)
            bb_width = (upper - lower) / mid * 100 if mid > 0 else 0

            old_mode = state.mode
            state.upper = upper
            state.lower = lower
            state.mid = mid
            state.bb_width_pct = bb_width
            state.trend_score = trend_score
            state.mode = mode

            mode_jp = {"range": "レンジ", "trend_up": "上昇トレンド", "trend_down": "下降トレンド"}
            mode_changed = f" ← 切替!" if old_mode != mode and old_mode != "unknown" else ""

            log(symbol,
                f"BB:{lower:.6f}-{upper:.6f} (幅:{bb_width:.1f}%) | "
                f"モード:{mode_jp.get(mode, mode)} (スコア:{trend_score:+.2f}){mode_changed}"
            )

        except Exception as e:
            log(symbol, f"レンジ更新エラー: {e}")

    def check_spread(self, symbol: str) -> bool:
        try:
            book = self.client.get_orderbook(symbol, limit=1)
            bids = book.get("b", [])
            asks = book.get("a", [])
            if not bids or not asks:
                return False
            bid = float(bids[0][0])
            ask = float(asks[0][0])
            mid = (bid + ask) / 2
            spread = (ask - bid) / mid * 100 if mid > 0 else 999
            return spread <= cfg.MAX_SPREAD_PCT
        except Exception:
            return True

    def get_entry_params(self, symbol: str, side: str) -> tuple[float, float]:
        """モードに応じたTP/SLを返す"""
        state = self.states[symbol]
        params = COIN_PARAMS.get(symbol, {"tp_range": 1.5, "sl_range": 0.5, "tp_trend": 2.0, "sl_trend": 0.5})

        if state.mode == "range":
            return params.get("tp_range", 1.5), params.get("sl_range", 0.5)
        else:
            return params.get("tp_trend", 2.0), params.get("sl_trend", 0.5)

    def check_entry(self, symbol: str, price: float):
        state = self.states[symbol]

        if state.in_position or state.upper == 0 or state.lower == 0:
            return

        # リスク管理
        if state.daily_trades >= cfg.MAX_DAILY_TRADES:
            return
        if state.last_loss_time > 0 and time.time() - state.last_loss_time < cfg.COOLDOWN_SEC:
            return

        # スプレッドチェック
        if not self.check_spread(symbol):
            return

        width = state.upper - state.lower
        offset = width * (cfg.ENTRY_OFFSET_PCT / 100)

        side = None

        if state.mode == "range":
            # === レンジモード: 逆張り ===
            # BB下限30%以下でロング、上限70%以上でショート
            range_pos = (price - state.lower) / width if width > 0 else 0.5
            if range_pos <= 0.30:
                side = "long"
            elif range_pos >= 0.70:
                side = "short"

        elif state.mode == "trend_up":
            # === 上昇トレンド: 順張りロング ===
            # BB下半分(60%以下)まで押したらロング
            range_pos = (price - state.lower) / width if width > 0 else 0.5
            if range_pos <= 0.60:
                side = "long"

        elif state.mode == "trend_down":
            # === 下降トレンド: 順張りショート ===
            # BB上半分(40%以上)まで戻したらショート
            range_pos = (price - state.lower) / width if width > 0 else 0.5
            if range_pos >= 0.40:
                side = "short"

        if side:
            self.open_position(symbol, side, price)

    def open_position(self, symbol: str, side: str, price: float):
        state = self.states[symbol]
        tp_pct, sl_pct = self.get_entry_params(symbol, side)

        if side == "long":
            tp_price = price * (1 + tp_pct / 100)
            sl_price = price * (1 - sl_pct / 100)
            order_side = "Buy"
        else:
            tp_price = price * (1 - tp_pct / 100)
            sl_price = price * (1 + sl_pct / 100)
            order_side = "Sell"

        qty = calc_qty(price, self.available_balance, state)
        mode_jp = {"range": "逆張り", "trend_up": "順張り↑", "trend_down": "順張り↓"}

        log(symbol,
            f"{mode_jp.get(state.mode, '?')} {side.upper()} @ {price:.6f} "
            f"| TP:{tp_price:.6f} SL:{sl_price:.6f} | 数量:{qty} (倍率:{state.bet_multiplier:.1f}x)"
        )

        if not cfg.DRY_RUN:
            try:
                self.client.place_order(
                    symbol=symbol, side=order_side, qty=qty,
                    order_type="Market",
                    take_profit=round_price(tp_price, state.tick_size),
                    stop_loss=round_price(sl_price, state.tick_size),
                )
            except Exception as e:
                log(symbol, f"注文エラー: {e}")
                return

        state.in_position = True
        state.position_side = side
        state.entry_price = price
        state.entry_time = time.time()
        state.qty = qty
        state.daily_trades += 1

    def check_position(self, symbol: str, price: float):
        state = self.states[symbol]
        if not state.in_position:
            return

        if not cfg.DRY_RUN:
            try:
                positions = self.client.get_positions(symbol)
                has_pos = any(float(p.get("size", 0)) > 0 for p in positions)
                if not has_pos:
                    self._close_position(symbol, price)
            except Exception:
                pass
        else:
            tp_pct, sl_pct = self.get_entry_params(symbol, state.position_side)

            if state.position_side == "long":
                tp_hit = price >= state.entry_price * (1 + tp_pct / 100)
                sl_hit = price <= state.entry_price * (1 - sl_pct / 100)
            else:
                tp_hit = price <= state.entry_price * (1 - tp_pct / 100)
                sl_hit = price >= state.entry_price * (1 + sl_pct / 100)

            if tp_hit:
                self._record_trade(symbol, tp_pct, price, "tp")
            elif sl_hit:
                self._record_trade(symbol, -sl_pct, price, "sl")
                state.last_loss_time = time.time()

    def _close_position(self, symbol: str, price: float):
        state = self.states[symbol]
        if state.position_side == "long":
            pnl_pct = (price - state.entry_price) / state.entry_price * 100
        else:
            pnl_pct = (state.entry_price - price) / state.entry_price * 100

        if pnl_pct < 0:
            state.last_loss_time = time.time()
        self._record_trade(symbol, pnl_pct, price, "tp" if pnl_pct > 0 else "sl")

    def _record_trade(self, symbol: str, pnl_pct: float, exit_price: float, reason: str):
        state = self.states[symbol]
        qty_float = float(state.qty)
        pnl_usd = state.entry_price * qty_float * (pnl_pct / 100)
        elapsed = time.time() - state.entry_time

        # 固定ベット(1.0倍)だった場合のPnL計算（比較用）
        base_qty_float = qty_float / state.bet_multiplier if state.bet_multiplier > 0 else qty_float
        pnl_usd_fixed = state.entry_price * base_qty_float * (pnl_pct / 100)
        state.pnl_usd_fixed += pnl_usd_fixed

        state.pnl_usd += pnl_usd
        if pnl_pct > 0:
            state.wins += 1
            # 勝ち → 倍率 -0.5 (下限1.0)
            state.bet_multiplier = max(1.0, state.bet_multiplier - 0.5)
        else:
            state.losses += 1
            # 負け → 倍率 +0.1
            state.bet_multiplier += 0.1

        trade = {
            "time": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol, "mode": state.mode,
            "side": state.position_side,
            "entry": state.entry_price, "exit": exit_price,
            "pnl_pct": round(pnl_pct, 4), "pnl_usd": round(pnl_usd, 4),
            "pnl_usd_fixed": round(pnl_usd_fixed, 4),
            "bet_mult": round(state.bet_multiplier, 1),
            "reason": reason, "hold_sec": round(elapsed),
        }
        state.trade_history.append(trade)

        # JSONログ
        try:
            log_path = Path("multi_trades.json")
            history = json.loads(log_path.read_text()) if log_path.exists() else []
            history.append(trade)
            log_path.write_text(json.dumps(history, indent=2))
        except Exception:
            pass

        icon = "WIN" if pnl_pct > 0 else "LOSS"
        mode_jp = {"range": "逆張", "trend_up": "順張↑", "trend_down": "順張↓"}
        log(symbol,
            f"{icon} {mode_jp.get(state.mode, '?')} {state.position_side.upper()} "
            f"{state.entry_price:.6f}→{exit_price:.6f} | {pnl_pct:+.2f}% (${pnl_usd:+.2f}) "
            f"| {elapsed:.0f}秒 | 累計:${state.pnl_usd:+.2f} | 次倍率:{state.bet_multiplier:.1f}x"
        )

        state.in_position = False
        state.position_side = ""
        state.entry_price = 0.0

    def print_dashboard(self):
        """全通貨のダッシュボード"""
        total_pnl = 0
        total_pnl_fixed = 0
        total_trades = 0
        lines = []
        for sym, s in self.states.items():
            mode_icon = {"range": "⇄", "trend_up": "↑", "trend_down": "↓"}.get(s.mode, "?")
            pos = ""
            if s.in_position:
                pos = f" {s.position_side[0].upper()}@{s.entry_price:.4f}"

            wr = s.wins / max(s.wins + s.losses, 1) * 100
            total_pnl += s.pnl_usd
            total_pnl_fixed += s.pnl_usd_fixed
            total_trades += s.wins + s.losses
            lines.append(
                f"  {sym:12s} {mode_icon} BB幅:{s.bb_width_pct:>4.1f}% "
                f"| {s.wins}W{s.losses}L {wr:>4.0f}% ${s.pnl_usd:>+6.2f} "
                f"(固定:${s.pnl_usd_fixed:>+5.2f}) 倍率:{s.bet_multiplier:.1f}x{pos}"
            )

        diff = total_pnl - total_pnl_fixed
        diff_label = f"差額:${diff:+.2f}" if total_trades > 0 else ""
        print(f"\r\n{'='*75}")
        print(f"  ダッシュボード | プログレ: ${total_pnl:+.2f} | 固定: ${total_pnl_fixed:+.2f} | {diff_label} | {total_trades}回")
        print(f"{'='*75}")
        for line in lines:
            print(line)
        print(f"{'='*75}")

    def run(self):
        print(f"{'='*65}")
        print(f"  マルチ通貨アダプティブスキャルパー")
        print(f"  モード: {'DRY RUN' if cfg.DRY_RUN else 'LIVE'}")
        print(f"  通貨: {', '.join(SYMBOLS)}")
        print(f"  レバレッジ: {cfg.LEVERAGE}x")
        print(f"  戦略: レンジ→逆張り / トレンド→順張り (自動切替)")
        print(f"{'='*65}")

        # 初期化
        for sym in SYMBOLS:
            if not self.init_coin(sym):
                print(f"  {sym} 初期化失敗、スキップ")

        if not self.states:
            print("初期化できた通貨がありません")
            return

        # レバレッジ設定
        if not cfg.DRY_RUN:
            for sym in self.states:
                try:
                    self.client.set_leverage(sym, cfg.LEVERAGE)
                except Exception:
                    pass

        # 残高取得
        if not cfg.DRY_RUN:
            try:
                bal = self.client.get_wallet_balance()
                coins = bal.get("list", [{}])[0].get("coin", [])
                usdt = next((c for c in coins if c.get("coin") == "USDT"), {})
                self.available_balance = float(usdt.get("availableToWithdraw", 100))
            except Exception:
                self.available_balance = 100
        else:
            self.available_balance = 100

        # 初回レンジ計算
        for sym in self.states:
            self.update_range(sym)
            time.sleep(0.3)

        self.running = True
        last_range_update = time.time()
        last_dashboard = time.time()

        try:
            while self.running:
                now = time.time()

                # レンジ定期更新
                if now - last_range_update > cfg.RANGE_UPDATE_SEC:
                    for sym in self.states:
                        self.update_range(sym)
                        time.sleep(0.2)
                    last_range_update = now

                # ダッシュボード表示
                if now - last_dashboard > 60:
                    self.print_dashboard()
                    last_dashboard = now

                # 各通貨の価格チェック
                for sym in list(self.states.keys()):
                    try:
                        ticker = self.client.get_ticker(sym)
                        price = float(ticker.get("lastPrice", 0))
                        if price <= 0:
                            continue

                        state = self.states[sym]
                        if state.in_position:
                            self.check_position(sym, price)
                        else:
                            self.check_entry(sym, price)

                    except Exception as e:
                        log(sym, f"エラー: {e}")

                    time.sleep(0.1)  # レート制限対策

                time.sleep(cfg.POLL_INTERVAL)

        except KeyboardInterrupt:
            print()
            self.print_dashboard()
            print("\nボット停止")


if __name__ == "__main__":
    bot = MultiScalper()
    bot.run()
