"""ペーパートレード Runner: Bitget の実価格を取りつつ注文は出さず、
シグナル発火と仮想 PnL を JSONL ログに記録する.

Usage:
    # M15 で 1 シンボル paper run (デフォルト 1分ごとにポーリング)
    python3 backtest/paper_runner.py --symbol BTCUSDT --tf 15m \\
        --set results/best_btcusdt_trend.set --interval 60

    # 1 回だけ実行 (cron で 15分毎に呼び出す想定)
    python3 backtest/paper_runner.py --symbol BTCUSDT --tf 15m \\
        --set results/best_btcusdt_trend.set --once

ログ:
    logs/paper/<symbol>_<tf>_signals.jsonl   - 全シグナル + 仮想エントリ/エグジット
    logs/paper/<symbol>_<tf>_state.json      - 現在の仮想ポジション
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from bitget_public import BitgetConfig, BitgetPublic
from compare_fees import load_set, make_params
from strategy import Params, prepare


REPO = Path(__file__).resolve().parent.parent


@dataclass
class PaperPosition:
    side: str           # "long"/"short"
    entry_time: str
    entry_price: float
    qty: float
    sl: float
    tp: float            # 0 = no TP (trail-only)


@dataclass
class PaperState:
    symbol: str
    tf: str
    open_position: PaperPosition | None = None
    consec_losses: int = 0
    cooldown_until: str | None = None
    realized_pnl_total: float = 0.0
    n_trades: int = 0
    n_wins: int = 0


def load_state(path: Path, sym: str, tf: str) -> PaperState:
    if path.exists():
        d = json.loads(path.read_text())
        if d.get("open_position"):
            d["open_position"] = PaperPosition(**d["open_position"])
        return PaperState(**d)
    return PaperState(symbol=sym, tf=tf)


def save_state(path: Path, st: PaperState):
    path.parent.mkdir(parents=True, exist_ok=True)
    d = asdict(st)
    path.write_text(json.dumps(d, indent=2, default=str))


def append_log(path: Path, entry: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


# ------------------------------- core -------------------------------

def fetch_recent(cli: BitgetPublic, sym: str, tf: str, lookback_bars: int = 300) -> pd.DataFrame:
    end = pd.Timestamp.utcnow()
    minutes = {"1m":1,"5m":5,"15m":15,"30m":30,"1h":60,"4h":240,"1d":1440}[tf]
    start = end - pd.Timedelta(minutes=minutes * lookback_bars)
    return cli.fetch_ohlcv_range(sym, tf,
                                 start.strftime("%Y-%m-%dT%H:%M:%S"),
                                 end.strftime("%Y-%m-%dT%H:%M:%S"))


def signal_check(prev_row, atr_avg: float, p: Params) -> tuple[bool, bool, dict]:
    """前バー確定値からシグナル判定. ロング/ショート可否と詳細を返す."""
    if pd.isna(prev_row.get("ema_f")) or pd.isna(prev_row.get("atr")):
        return False, False, {"reason": "indicators_not_ready"}
    vol_ok = prev_row["atr"] >= atr_avg * p.atr_min_mult
    adx_ok = (p.adx_min <= 0) or (prev_row.get("adx", 100.0) >= p.adx_min)
    htf_dir = int(prev_row.get("htf_dir", 0))
    htf_long_ok  = (p.htf_ratio <= 1) or (htf_dir >= 0)
    htf_short_ok = (p.htf_ratio <= 1) or (htf_dir <= 0)
    buy = ((prev_row["ema_f"] > prev_row["ema_s"]) and (prev_row["rsi"] >= p.rsi_buy_min)
           and vol_ok and adx_ok and htf_long_ok)
    sell = ((prev_row["ema_f"] < prev_row["ema_s"]) and (prev_row["rsi"] <= p.rsi_sell_max)
            and vol_ok and adx_ok and htf_short_ok)
    detail = {
        "ema_f": float(prev_row["ema_f"]), "ema_s": float(prev_row["ema_s"]),
        "rsi": float(prev_row["rsi"]), "atr": float(prev_row["atr"]),
        "atr_avg": float(atr_avg), "adx": float(prev_row.get("adx", 0.0)),
        "htf_dir": htf_dir, "vol_ok": bool(vol_ok), "adx_ok": bool(adx_ok),
    }
    return buy, sell, detail


def manage_position(state: PaperState, last_row, atr_now: float, p: Params,
                    fee_each: float, slip: float, log_path: Path) -> bool:
    """SL/TP/トレールを判定. クローズしたら True."""
    pos = state.open_position
    if pos is None:
        return False
    high, low = float(last_row["high"]), float(last_row["low"])
    trail_start = atr_now * p.trail_start_atr
    trail_step  = atr_now * p.trail_step_atr
    closed = False; reason = ""; exit_px = 0.0

    if pos.side == "long":
        # トレーリング
        profit = high - pos.entry_price
        if trail_start > 0 and profit >= trail_start:
            new_sl = high - trail_step
            if new_sl > pos.sl:
                pos.sl = new_sl
        # SL/TP
        if low <= pos.sl:
            exit_px = pos.sl * (1 - slip); reason = "SL"; closed = True
        elif pos.tp > 0 and high >= pos.tp:
            exit_px = pos.tp * (1 - slip); reason = "TP"; closed = True
    else:  # short
        profit = pos.entry_price - low
        if trail_start > 0 and profit >= trail_start:
            new_sl = low + trail_step
            if pos.sl == 0 or new_sl < pos.sl:
                pos.sl = new_sl
        if high >= pos.sl:
            exit_px = pos.sl * (1 + slip); reason = "SL"; closed = True
        elif pos.tp > 0 and low <= pos.tp:
            exit_px = pos.tp * (1 + slip); reason = "TP"; closed = True

    if closed:
        sign = 1 if pos.side == "long" else -1
        pnl = sign * (exit_px - pos.entry_price) * pos.qty \
              - (pos.entry_price + exit_px) * pos.qty * fee_each
        state.realized_pnl_total += pnl
        state.n_trades += 1
        if pnl > 0:
            state.n_wins += 1
            state.consec_losses = 0
        elif pnl < 0:
            state.consec_losses += 1
        append_log(log_path, dict(
            ts=datetime.now(timezone.utc).isoformat(),
            event="close", side=pos.side, reason=reason,
            entry_time=pos.entry_time, entry=pos.entry_price,
            exit=exit_px, qty=pos.qty, pnl=pnl,
            realized_total=state.realized_pnl_total,
        ))
        state.open_position = None
    return closed


def step(cli: BitgetPublic, sym: str, tf: str, p: Params,
         state: PaperState, log_path: Path) -> dict:
    df = fetch_recent(cli, sym, tf, lookback_bars=300)
    if len(df) < max(p.ema_slow * 2, 100):
        return {"status": "insufficient_data", "bars": len(df)}
    df = df.rename_axis("time")
    prep = prepare(df, p)
    prep["atr_avg20"] = prep["atr"].rolling(20, min_periods=5).mean()
    if len(prep) < 3:
        return {"status": "insufficient_data"}

    last = prep.iloc[-1]
    prev = prep.iloc[-2]
    atr_now = float(last["atr"]) if not pd.isna(last["atr"]) else 0.0
    atr_avg = float(prev["atr_avg20"]) if not pd.isna(prev["atr_avg20"]) else 0.0
    fee_each = p.fee_rt_pct / 200.0
    slip = p.slippage_pct / 100.0

    # 既存ポジション管理
    closed = manage_position(state, last, atr_now, p, fee_each, slip, log_path)

    # クールダウン中なら新規スキップ
    if state.cooldown_until:
        cd = pd.Timestamp(state.cooldown_until)
        if pd.Timestamp.utcnow().tz_localize(None) < cd:
            return {"status": "cooldown", "until": state.cooldown_until}
        else:
            state.cooldown_until = None

    # 連敗閾値到達でクールダウン
    if state.consec_losses >= p.max_consec_loss:
        cd_until = pd.Timestamp.utcnow().tz_localize(None) + pd.Timedelta(minutes=p.cooldown_bars * 15)
        state.cooldown_until = cd_until.isoformat()
        state.consec_losses = 0

    if state.open_position is not None:
        return {"status": "in_position", "closed_this_step": closed}

    # シグナル判定
    buy, sell, detail = signal_check(prev.to_dict(), atr_avg, p)
    if not (buy or sell):
        return {"status": "no_signal", **detail}

    entry_raw = float(last["open"])
    atr_e = float(prev["atr"])
    tp_d = atr_e * p.tp_atr_mult
    sl_d = atr_e * p.sl_atr_mult
    qty = p.fixed_qty if p.risk_pct <= 0 else max(p.fixed_qty * 0.1, p.risk_pct * 100 / max(sl_d, 1e-9))

    if buy:
        entry = entry_raw * (1 + slip)
        sl = entry - sl_d
        tp = 0.0 if p.trail_only else entry + tp_d
        state.open_position = PaperPosition("long", str(last.name), entry, qty, sl, tp)
    else:
        entry = entry_raw * (1 - slip)
        sl = entry + sl_d
        tp = 0.0 if p.trail_only else entry - tp_d
        state.open_position = PaperPosition("short", str(last.name), entry, qty, sl, tp)

    append_log(log_path, dict(
        ts=datetime.now(timezone.utc).isoformat(),
        event="open", side=state.open_position.side,
        bar_time=str(last.name), entry=state.open_position.entry_price,
        sl=state.open_position.sl, tp=state.open_position.tp,
        qty=state.open_position.qty, **detail,
    ))
    return {"status": "opened", "side": state.open_position.side}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--tf", default="15m")
    ap.add_argument("--set", required=True)
    ap.add_argument("--interval", type=int, default=60,
                    help="ポーリング間隔(秒). --once と排他.")
    ap.add_argument("--once", action="store_true",
                    help="1回だけ実行して終了")
    ap.add_argument("--fee", type=float, default=0.04)
    ap.add_argument("--slip", type=float, default=0.01)
    ap.add_argument("--logs-dir", default="logs/paper")
    args = ap.parse_args()

    s = load_set(Path(args.set))
    p = make_params(s)
    p = replace(p, fee_rt_pct=args.fee, slippage_pct=args.slip)
    cli = BitgetPublic(BitgetConfig(product_type="spot"))

    log_path  = REPO / args.logs_dir / f"{args.symbol}_{args.tf}_signals.jsonl"
    state_path = REPO / args.logs_dir / f"{args.symbol}_{args.tf}_state.json"
    state = load_state(state_path, args.symbol, args.tf)

    print(f"Paper runner: {args.symbol} {args.tf}  set={args.set}")
    print(f"  open_pos={state.open_position}  realized={state.realized_pnl_total:.2f}")

    while True:
        try:
            r = step(cli, args.symbol, args.tf, p, state, log_path)
            ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
            print(f"  [{ts}] {r}", flush=True)
        except Exception as e:
            print(f"  ERROR: {e}", flush=True)
        save_state(state_path, state)
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
