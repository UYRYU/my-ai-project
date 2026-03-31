"""Bybit マルチ通貨 アダプティブスキャルパー

レンジ相場 → 逆張り (BBバウンス)
トレンド相場 → 順張り (BBブレイクアウト)
自動判定で切り替え + 5通貨同時対応
"""

import math
import statistics
import time
import json
import threading
import requests
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path

from bybit_client import BybitClient
import bybit_config as cfg


# === 自動選定の設定 ===
AUTO_ROTATE = getattr(cfg, 'AUTO_ROTATE', True)      # 自動ローテーションON/OFF
ROTATE_INTERVAL = getattr(cfg, 'ROTATE_INTERVAL', 7200)  # スキャン間隔(秒) = 2時間
MAX_COINS = getattr(cfg, 'MAX_COINS', 5)              # 同時運用数
MIN_VOLUME_USDT = getattr(cfg, 'MIN_VOLUME_USDT', 500_000)  # 最低出来高


# === 通貨別最適パラメータ (デフォルト値、自動選定時はこれを使う) ===
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


# === ボラティリティスキャナー ===
def scan_volatile_coins(top_n: int = 10) -> list[dict]:
    """Bybit先物からボラの高い通貨TOP Nを自動選定"""
    try:
        resp = requests.get(
            "https://api.bybit.com/v5/market/tickers?category=linear",
            timeout=15,
        )
        resp.raise_for_status()
        tickers = resp.json().get("result", {}).get("list", [])
    except Exception as e:
        log("SCANNER", f"ティッカー取得エラー: {e}")
        return []

    candidates = []
    for t in tickers:
        sym = t.get("symbol", "")
        if not sym.endswith("USDT"):
            continue
        try:
            high = float(t.get("highPrice24h", 0))
            low = float(t.get("lowPrice24h", 0))
            last = float(t.get("lastPrice", 0))
            vol = float(t.get("turnover24h", 0))
            if low <= 0 or last <= 0 or vol < MIN_VOLUME_USDT:
                continue
            vol_pct = ((high - low) / low) * 100
            if vol_pct < 3:  # ボラ3%以下は除外
                continue
            candidates.append({
                "symbol": sym, "price": last,
                "vol_pct": vol_pct, "volume": vol,
            })
        except (ValueError, TypeError):
            continue

    if not candidates:
        return []

    # K線分析で上位候補を詳細チェック
    # まずボラ×出来高で上位30に絞る
    candidates.sort(key=lambda x: x["vol_pct"] * math.log10(max(x["volume"], 1)), reverse=True)
    candidates = candidates[:30]

    results = []
    for c in candidates:
        try:
            resp = requests.get(
                "https://api.bybit.com/v5/market/kline",
                params={"category": "linear", "symbol": c["symbol"], "interval": "15", "limit": 96},
                timeout=15,
            )
            resp.raise_for_status()
            klines_raw = resp.json().get("result", {}).get("list", [])
            if len(klines_raw) < 20:
                continue
            closes = [float(k[4]) for k in reversed(klines_raw)]

            # 中央クロス回数
            median_price = statistics.median(closes)
            cross_count = 0
            above = closes[0] > median_price
            for cl in closes[1:]:
                now_above = cl > median_price
                if now_above != above:
                    cross_count += 1
                    above = now_above

            # BB幅
            recent = closes[-20:]
            mean = statistics.mean(recent)
            std = statistics.stdev(recent) if len(recent) > 1 else 0
            bb_width = (std * 4 / mean * 100) if mean > 0 else 0

            # スコア: ボラ + 出来高 + BB幅 + クロス回数
            vol_score = min(c["vol_pct"] / 20, 1.0)
            vol_usd_score = min(math.log10(max(c["volume"], 1)) / 8, 1.0)
            bb_score = min(bb_width / 10, 1.0)
            cross_score = min(cross_count / 15, 1.0)

            total = vol_score * 25 + vol_usd_score * 20 + bb_score * 30 + cross_score * 25

            c["score"] = round(total, 1)
            c["bb_width"] = round(bb_width, 1)
            c["cross_count"] = cross_count
            results.append(c)

            time.sleep(0.2)
        except Exception:
            continue

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_n]


# === 取引対象通貨 ===
SYMBOLS = getattr(cfg, 'SYMBOLS', [cfg.SYMBOL])
if isinstance(SYMBOLS, str):
    SYMBOLS = [SYMBOLS]


@dataclass
class ShadowPosition:
    """パターンB仮想ポジション"""
    side: str = ""
    entry_price: float = 0.0
    entry_time: float = 0.0
    mode: str = ""


@dataclass
class ShadowStats:
    """パターンB（ブレイクアウト付き）の仮想トレード統計"""
    wins: int = 0
    losses: int = 0
    pnl_usd: float = 0.0
    bet_multiplier: float = 1.0
    pnl_usd_fixed: float = 0.0
    position: ShadowPosition = field(default_factory=ShadowPosition)
    last_loss_time: float = 0.0


class MultiScalper:
    def __init__(self):
        self.client = BybitClient(cfg.API_KEY, cfg.API_SECRET)
        self.states: dict[str, CoinState] = {}
        self.shadows: dict[str, ShadowStats] = {}  # パターンB仮想トレード
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
            self.shadows[symbol] = ShadowStats()
            log(symbol, f"初期化OK: 最小={state.min_qty}, 刻み={state.qty_step}")
            return True
        except Exception as e:
            log(symbol, f"初期化エラー: {e}")
            return False

    def rotate_coins(self):
        """ボラの高い通貨を自動選定して入れ替え"""
        log("SCANNER", "ボラティリティスキャン開始...")
        top = scan_volatile_coins(top_n=MAX_COINS * 2)
        if not top:
            log("SCANNER", "スキャン結果なし、現状維持")
            return

        # 表示
        log("SCANNER", f"TOP{len(top)}:")
        for i, c in enumerate(top[:MAX_COINS * 2], 1):
            log("SCANNER", f"  {i}. {c['symbol']} ボラ:{c['vol_pct']:.1f}% BB幅:{c['bb_width']}% "
                f"往復:{c['cross_count']}回 出来高:{c['volume']/1e6:.1f}M スコア:{c['score']}")

        new_symbols = [c["symbol"] for c in top[:MAX_COINS]]

        # ポジション保有中のコインは残す
        keep = set()
        remove = set()
        for sym, state in self.states.items():
            if state.in_position:
                keep.add(sym)
            elif sym not in new_symbols:
                remove.add(sym)
            else:
                keep.add(sym)

        # シャドウポジション保有中も考慮
        for sym, shadow in self.shadows.items():
            if shadow.position.side:
                keep.add(sym)
                remove.discard(sym)

        # 削除
        for sym in remove:
            log("SCANNER", f"除外: {sym}")
            del self.states[sym]
            if sym in self.shadows:
                del self.shadows[sym]

        # 新規追加 (MAX_COINSまで)
        current = set(self.states.keys())
        for c in top:
            if len(current) >= MAX_COINS:
                break
            sym = c["symbol"]
            if sym not in current:
                if self.init_coin(sym):
                    self.update_range(sym)
                    current.add(sym)
                    log("SCANNER", f"追加: {sym} (ボラ:{c['vol_pct']:.1f}% スコア:{c['score']})")
                time.sleep(0.3)

        active = list(self.states.keys())
        log("SCANNER", f"現在の運用通貨: {', '.join(active)} ({len(active)}個)")

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

    def shadow_check(self, symbol: str, price: float):
        """パターンB: ブレイクアウト付きロジックの仮想トレード"""
        state = self.states[symbol]
        shadow = self.shadows[symbol]

        if shadow.position.side:
            # 仮想ポジション決済チェック
            tp_pct, sl_pct = self.get_entry_params(symbol, shadow.position.side)
            if shadow.position.side == "long":
                tp_hit = price >= shadow.position.entry_price * (1 + tp_pct / 100)
                sl_hit = price <= shadow.position.entry_price * (1 - sl_pct / 100)
            else:
                tp_hit = price <= shadow.position.entry_price * (1 - tp_pct / 100)
                sl_hit = price >= shadow.position.entry_price * (1 + sl_pct / 100)

            if tp_hit or sl_hit:
                pnl_pct = tp_pct if tp_hit else -sl_pct
                base_qty = float(calc_qty(shadow.position.entry_price, self.available_balance, state, use_multiplier=False))
                pnl_fixed = shadow.position.entry_price * base_qty * (pnl_pct / 100)
                pnl_prog = shadow.position.entry_price * base_qty * shadow.bet_multiplier * (pnl_pct / 100)
                shadow.pnl_usd += pnl_prog
                shadow.pnl_usd_fixed += pnl_fixed
                if tp_hit:
                    shadow.wins += 1
                    shadow.bet_multiplier = max(1.0, shadow.bet_multiplier - 0.5)
                else:
                    shadow.losses += 1
                    shadow.bet_multiplier += 0.1
                    shadow.last_loss_time = time.time()
                shadow.position = ShadowPosition()
        else:
            # 仮想エントリーチェック
            if state.upper == 0 or state.lower == 0:
                return
            if shadow.last_loss_time > 0 and time.time() - shadow.last_loss_time < cfg.COOLDOWN_SEC:
                return

            width = state.upper - state.lower
            side = None
            range_pos = (price - state.lower) / width if width > 0 else 0.5

            if state.mode == "range":
                if range_pos <= 0.30:
                    side = "long"
                elif range_pos >= 0.70:
                    side = "short"
            elif state.mode == "trend_up":
                if range_pos <= 0.60:
                    side = "long"
                elif range_pos >= 1.0:
                    side = "long"  # ブレイクアウト
            elif state.mode == "trend_down":
                if range_pos >= 0.40:
                    side = "short"
                elif range_pos <= 0.0:
                    side = "short"  # ブレイクアウト

            if side:
                shadow.position = ShadowPosition(
                    side=side, entry_price=price,
                    entry_time=time.time(), mode=state.mode,
                )

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

        # パターンB集計
        total_b_pnl = 0
        total_b_trades = 0
        b_lines = []
        for sym, sh in self.shadows.items():
            s = self.states[sym]
            mode_icon = {"range": "⇄", "trend_up": "↑", "trend_down": "↓"}.get(s.mode, "?")
            b_total = sh.wins + sh.losses
            wr = sh.wins / max(b_total, 1) * 100
            total_b_pnl += sh.pnl_usd
            total_b_trades += b_total
            pos = f" {sh.position.side[0].upper()}@{sh.position.entry_price:.4f}" if sh.position.side else ""
            b_lines.append(
                f"  {sym:12s} {mode_icon} "
                f"| {sh.wins}W{sh.losses}L {wr:>4.0f}% ${sh.pnl_usd:>+6.2f} "
                f"倍率:{sh.bet_multiplier:.1f}x{pos}"
            )

        print(f"\r\n{'='*75}")
        print(f"  【A】押し目/戻りのみ  | PnL: ${total_pnl:+.2f} (固定:${total_pnl_fixed:+.2f}) | {total_trades}回")
        print(f"{'='*75}")
        for line in lines:
            print(line)
        print(f"{'='*75}")
        print(f"  【B】+ブレイクアウト   | PnL: ${total_b_pnl:+.2f} | {total_b_trades}回")
        print(f"{'='*75}")
        for line in b_lines:
            print(line)
        winner = "A" if total_pnl >= total_b_pnl else "B"
        diff = abs(total_pnl - total_b_pnl)
        print(f"  >>> 現在の勝者: パターン{winner} (差額:${diff:.2f})")
        print(f"{'='*75}")

    def run(self):
        rotate_label = "ON" if AUTO_ROTATE else "OFF"
        print(f"{'='*65}")
        print(f"  マルチ通貨アダプティブスキャルパー")
        print(f"  モード: {'DRY RUN' if cfg.DRY_RUN else 'LIVE'}")
        print(f"  通貨: {', '.join(SYMBOLS)}")
        print(f"  レバレッジ: {cfg.LEVERAGE}x")
        print(f"  戦略: レンジ→逆張り / トレンド→順張り (自動切替)")
        print(f"  自動銘柄選定: {rotate_label} ({ROTATE_INTERVAL//3600}h間隔)")
        print(f"{'='*65}")

        # 初期化: AUTO_ROTATEならスキャンして選定、そうでなければ設定通り
        if AUTO_ROTATE:
            log("SCANNER", "初回銘柄スキャン...")
            top = scan_volatile_coins(top_n=MAX_COINS * 2)
            if top:
                init_symbols = [c["symbol"] for c in top[:MAX_COINS]]
                log("SCANNER", f"自動選定: {', '.join(init_symbols)}")
            else:
                init_symbols = list(SYMBOLS)
                log("SCANNER", f"スキャン失敗、デフォルト使用: {', '.join(init_symbols)}")
        else:
            init_symbols = list(SYMBOLS)

        for sym in init_symbols:
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
        last_rotate = time.time()

        try:
            while self.running:
                now = time.time()

                # 銘柄自動ローテーション
                if AUTO_ROTATE and now - last_rotate > ROTATE_INTERVAL:
                    self.rotate_coins()
                    last_rotate = now

                # レンジ定期更新
                if now - last_range_update > cfg.RANGE_UPDATE_SEC:
                    for sym in list(self.states.keys()):
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

                        # パターンB仮想トレード
                        if sym in self.shadows:
                            self.shadow_check(sym, price)

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
