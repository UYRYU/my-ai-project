"""
高速スキャン (WF なし、全年通しテスト)。
進捗を随時 pickle に保存 → 途中停止しても回収可能。
"""
import sys, os, time, pickle
sys.path.insert(0, "/home/user/my-ai-project")
import numpy as np, pandas as pd
from trading.strategies_v2 import *
from trading.backtest import _simulate_trade

XM_STD = {"xauusd": 0.35, "xagusd": 0.035, "wtiusd": 0.05,
           "eurusd": 0.00017, "usdjpy": 0.016, "gbpusd": 0.00021,
           "btcusd": 5.0, "ethusd": 0.50}
ALL_ASSETS = {
    "xauusd": list(range(2015,2019)), "xagusd": list(range(2015,2019)),
    "wtiusd": list(range(2015,2019)), "eurusd": list(range(2015,2019)),
    "usdjpy": list(range(2015,2019)), "gbpusd": list(range(2015,2019)),
    "btcusd": list(range(2017,2025)), "ethusd": list(range(2017,2020)),
}
PROG = "/tmp/scan_progress.pkl"
WINS = "/tmp/scan_winners.pkl"

def load(pair, year):
    for p in [f"data/{pair}_15m_{year}.csv", f"data/{pair}_15m_{year}q1.csv"]:
        if os.path.exists(p):
            df = pd.read_csv(p, index_col=0, parse_dates=True)
            df.columns = [c.lower() for c in df.columns]
            return df
    return None

def rs(df, tf):
    if tf == "15min": return df
    return df.resample(tf).agg({"open":"first","high":"max","low":"min","close":"last"}).dropna()

def bt(df, sigs):
    trades = []; ip = -1
    for s in sigs:
        if s.entry_index <= ip: continue
        t = _simulate_trade(df, s)
        if t is None: continue
        trades.append(t)
        ei = df.index.get_loc(t.exit_time)
        if isinstance(ei, slice): ei = ei.stop - 1
        ip = int(ei)
    return trades

STRATS = []
for rp in [7,14]:
    for ep in [20,50]:
        for rl,rh in [(30,70),(25,75)]:
            for rr in [1.0,2.0,3.0]:
                for sw in [20,50]:
                    STRATS.append(("rsi", dict(rsi_period=rp,ema_period=ep,rsi_low=rl,rsi_high=rh,swing_lookback=sw,rr_ratio=rr)))
for bs in [1.5,2.0]:
    for ep in [20,50]:
        for rr in [1.0,2.0,3.0]:
            for sw in [20,50]:
                STRATS.append(("bollinger", dict(bb_period=20,bb_std=bs,ema_period=ep,swing_lookback=sw,rr_ratio=rr)))
for f,sl in [(5,20),(10,50),(20,100)]:
    for rr in [1.0,2.0,3.0]:
        for sw in [20,50]:
            STRATS.append(("ema_cross", dict(fast_ema=f,slow_ema=sl,swing_lookback=sw,rr_ratio=rr)))
for lb in [20,50]:
    for rr in [1.0,2.0,3.0]:
        for sw in [20,50]:
            STRATS.append(("breakout", dict(lookback=lb,swing_lookback=sw,rr_ratio=rr)))
for f,sl,sg in [(12,26,9),(8,21,5)]:
    for rr in [1.0,2.0,3.0]:
        for sw in [20,50]:
            STRATS.append(("macd", dict(fast=f,slow=sl,signal_period=sg,ema_trend=50,swing_lookback=sw,rr_ratio=rr)))
for ep in [20,50]:
    for th in [1.0,2.0]:
        for rr in [0.5,1.0]:
            for sw in [20,50]:
                STRATS.append(("mean_rev", dict(ema_period=ep,threshold_pct=th,swing_lookback=sw,rr_ratio=rr)))
for rr in [1.0,2.0,3.0]:
    for sw in [20,50]:
        STRATS.append(("rsi_bb", dict(rsi_period=14,rsi_low=30,rsi_high=70,bb_period=20,bb_std=2.0,swing_lookback=sw,rr_ratio=rr)))

FUNCS = {"rsi": signals_rsi, "bollinger": signals_bollinger, "ema_cross": signals_ema_cross,
         "breakout": signals_breakout, "macd": signals_macd, "mean_rev": signals_mean_reversion,
         "rsi_bb": signals_rsi_bb}
tfs = ["15min","30min","1h","4h"]

# レジューム
done_set = set()
if os.path.exists(PROG):
    done_set = pickle.load(open(PROG, "rb"))
    print(f"Resuming from {len(done_set)} done", flush=True)
winners = []
if os.path.exists(WINS):
    winners = pickle.load(open(WINS, "rb"))

t0 = time.time()
total = len(STRATS) * len(ALL_ASSETS) * len(tfs)
done = len(done_set)
save_every = 100
last_save = done

for idx, (strat_name, params) in enumerate(STRATS):
    func = FUNCS[strat_name]
    for asset in ALL_ASSETS:
        for tf in tfs:
            key = (idx, asset, tf)
            if key in done_set:
                continue

            spread = XM_STD.get(asset, 0)
            avail = [y for y in ALL_ASSETS[asset] if load(asset, y) is not None]
            all_t = []
            for y in avail:
                raw = load(asset, y)
                if raw is None: continue
                df = rs(raw, tf)
                if len(df) < 100: continue
                try:
                    sigs = func(df, **params)
                    trades = bt(df, sigs)
                except:
                    continue
                for t in trades:
                    sd = abs(t.entry_price - t.stop)
                    sr = spread / sd if sd > 0 else 0
                    all_t.append((t.entry_time, t.pnl_r, sr))

            if len(all_t) >= 20:
                all_t.sort()
                eq = 1000.0; pk = eq; dd = 0.0; gp = 0.0; gl = 0.0
                for ts, pr, sr_ in all_t:
                    ra = pr - sr_
                    if ra > 0: ra *= 0.90
                    eq += eq * 0.05 * ra
                    if ra > 0: gp += ra
                    else: gl -= ra
                    if eq > pk: pk = eq
                    d = (pk-eq)/pk*100 if pk>0 else 0
                    if d > dd: dd = d
                pf = gp/gl if gl > 0 else 999
                days = len(avail) * 365
                ann = ((eq/1000)**(365/days)-1)*100 if days>0 and eq>0 else -100
                mt = len(all_t)/(days/30)
                if ann >= 10 and pf >= 1.05:
                    winners.append({
                        "label": f"{strat_name}/{asset.upper()}/{tf}",
                        "strat": strat_name, "asset": asset, "tf": tf,
                        "eq":eq,"ann":ann,"dd":dd,"pf":pf,"trades":len(all_t),"monthly":mt,
                        "params": params, "raw_trades": all_t
                    })

            done_set.add(key)
            done += 1
            if done - last_save >= save_every:
                pickle.dump(done_set, open(PROG, "wb"))
                pickle.dump(winners, open(WINS, "wb"))
                last_save = done
                print(f"  {done}/{total} ({len(winners)} wins) {time.time()-t0:.0f}s", flush=True)

pickle.dump(done_set, open(PROG, "wb"))
pickle.dump(winners, open(WINS, "wb"))
print(f"\nDONE in {time.time()-t0:.0f}s. Total winners: {len(winners)}", flush=True)
