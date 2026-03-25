"""有望シグナル集中探索 Phase 2

前回の結果から勝ちパターンに全集中:
  - atr_break (maxPF=1.27) ← 最強
  - wick_reversal (PF=1.01, 唯一のPF≥1.0)
  - bb_bounce (maxPF=1.17)
  - donchian_break (maxPF=1.21)
  - hilo_break (maxPF=1.21)

勝ちパターン:
  - ATRベース損小利大 TP/SL
  - GBPJPY > EURJPY > USDJPY
  - newyork ≧ london
  - トレーリングストップ追加

目標: 平均PF≥1.0, 最大PF 1.3〜1.5
"""

import os
import sys
import itertools
import hashlib
import json
import logging
import random
from collections import Counter

import pandas as pd
import numpy as np
from tqdm import tqdm

from engine.strategy_generator import _make_name
from engine.configurable_strategy import ConfigurableStrategy
from data_loader import load_ohlc, discover_data_files
from metrics import evaluate_strategy
from engine.evolution import split_is_oos, _classify_session

logger = logging.getLogger(__name__)

ECN_SPREAD = 0.003
ECN_COMM = 0.0025
SPREAD_TESTS = [0.002, 0.003, 0.005, 0.010]

SYMBOLS = ["USDJPY", "EURJPY", "GBPJPY"]
TF = "M1"

# ================================================================
# 有望シグナルのみ × パラメータ大量バリエーション
# ================================================================

SIGNALS = [
    # --- atr_break: 前回最強 maxPF=1.27 ---
    {"type": "atr_break", "category": "breakout", "period": 5, "multiplier": 1.0},
    {"type": "atr_break", "category": "breakout", "period": 7, "multiplier": 1.0},
    {"type": "atr_break", "category": "breakout", "period": 7, "multiplier": 1.5},
    {"type": "atr_break", "category": "breakout", "period": 10, "multiplier": 1.0},
    {"type": "atr_break", "category": "breakout", "period": 10, "multiplier": 1.5},
    {"type": "atr_break", "category": "breakout", "period": 10, "multiplier": 2.0},
    {"type": "atr_break", "category": "breakout", "period": 14, "multiplier": 1.0},
    {"type": "atr_break", "category": "breakout", "period": 14, "multiplier": 1.5},
    {"type": "atr_break", "category": "breakout", "period": 14, "multiplier": 2.0},
    {"type": "atr_break", "category": "breakout", "period": 14, "multiplier": 2.5},
    {"type": "atr_break", "category": "breakout", "period": 20, "multiplier": 1.5},
    {"type": "atr_break", "category": "breakout", "period": 20, "multiplier": 2.0},

    # --- wick_reversal: 前回唯一PF≥1.0 ---
    {"type": "wick_reversal", "category": "mean_reversion", "wick_ratio": 1.0, "min_wick_atr": 0.3, "atr_period": 7},
    {"type": "wick_reversal", "category": "mean_reversion", "wick_ratio": 1.0, "min_wick_atr": 0.5, "atr_period": 7},
    {"type": "wick_reversal", "category": "mean_reversion", "wick_ratio": 1.0, "min_wick_atr": 0.8, "atr_period": 7},
    {"type": "wick_reversal", "category": "mean_reversion", "wick_ratio": 1.5, "min_wick_atr": 0.3, "atr_period": 10},
    {"type": "wick_reversal", "category": "mean_reversion", "wick_ratio": 1.5, "min_wick_atr": 0.5, "atr_period": 10},
    {"type": "wick_reversal", "category": "mean_reversion", "wick_ratio": 1.5, "min_wick_atr": 0.5, "atr_period": 14},
    {"type": "wick_reversal", "category": "mean_reversion", "wick_ratio": 2.0, "min_wick_atr": 0.3, "atr_period": 14},
    {"type": "wick_reversal", "category": "mean_reversion", "wick_ratio": 2.0, "min_wick_atr": 0.5, "atr_period": 14},
    {"type": "wick_reversal", "category": "mean_reversion", "wick_ratio": 2.5, "min_wick_atr": 0.3, "atr_period": 14},
    {"type": "wick_reversal", "category": "mean_reversion", "wick_ratio": 1.0, "min_wick_atr": 1.0, "atr_period": 10},

    # --- bb_bounce ---
    {"type": "bb_bounce", "category": "mean_reversion", "period": 10, "std_mult": 1.5},
    {"type": "bb_bounce", "category": "mean_reversion", "period": 10, "std_mult": 2.0},
    {"type": "bb_bounce", "category": "mean_reversion", "period": 14, "std_mult": 1.5},
    {"type": "bb_bounce", "category": "mean_reversion", "period": 14, "std_mult": 2.0},
    {"type": "bb_bounce", "category": "mean_reversion", "period": 20, "std_mult": 1.5},
    {"type": "bb_bounce", "category": "mean_reversion", "period": 20, "std_mult": 2.0},
    {"type": "bb_bounce", "category": "mean_reversion", "period": 20, "std_mult": 2.5},
    {"type": "bb_bounce", "category": "mean_reversion", "period": 30, "std_mult": 2.0},
    {"type": "bb_bounce", "category": "mean_reversion", "period": 30, "std_mult": 2.5},

    # --- donchian_break ---
    {"type": "donchian_break", "category": "breakout", "period": 5},
    {"type": "donchian_break", "category": "breakout", "period": 10},
    {"type": "donchian_break", "category": "breakout", "period": 15},
    {"type": "donchian_break", "category": "breakout", "period": 20},
    {"type": "donchian_break", "category": "breakout", "period": 30},

    # --- hilo_break ---
    {"type": "hilo_break", "category": "breakout", "lookback": 5, "confirm_bars": 1},
    {"type": "hilo_break", "category": "breakout", "lookback": 10, "confirm_bars": 1},
    {"type": "hilo_break", "category": "breakout", "lookback": 15, "confirm_bars": 1},
    {"type": "hilo_break", "category": "breakout", "lookback": 20, "confirm_bars": 1},
    {"type": "hilo_break", "category": "breakout", "lookback": 10, "confirm_bars": 2},
    {"type": "hilo_break", "category": "breakout", "lookback": 15, "confirm_bars": 2},
]

# ATRベース損小利大を中心にTP/SL
TPSL = [
    # ATR損小利大 (前回最強パターン)
    {"tp_type": "atr_mult", "tp_atr_mult": 2.0, "sl_type": "atr_mult", "sl_atr_mult": 1.0},
    {"tp_type": "atr_mult", "tp_atr_mult": 2.5, "sl_type": "atr_mult", "sl_atr_mult": 1.0},
    {"tp_type": "atr_mult", "tp_atr_mult": 3.0, "sl_type": "atr_mult", "sl_atr_mult": 1.0},
    {"tp_type": "atr_mult", "tp_atr_mult": 3.0, "sl_type": "atr_mult", "sl_atr_mult": 1.5},
    {"tp_type": "atr_mult", "tp_atr_mult": 4.0, "sl_type": "atr_mult", "sl_atr_mult": 1.0},
    {"tp_type": "atr_mult", "tp_atr_mult": 4.0, "sl_type": "atr_mult", "sl_atr_mult": 1.5},
    {"tp_type": "atr_mult", "tp_atr_mult": 5.0, "sl_type": "atr_mult", "sl_atr_mult": 1.5},
    {"tp_type": "atr_mult", "tp_atr_mult": 2.0, "sl_type": "atr_mult", "sl_atr_mult": 0.7},
    {"tp_type": "atr_mult", "tp_atr_mult": 3.0, "sl_type": "atr_mult", "sl_atr_mult": 0.7},
    # 固定pips損小利大
    {"tp_type": "fixed", "tp_pips": 0.15, "sl_type": "fixed", "sl_pips": 0.05},
    {"tp_type": "fixed", "tp_pips": 0.15, "sl_type": "fixed", "sl_pips": 0.07},
    {"tp_type": "fixed", "tp_pips": 0.20, "sl_type": "fixed", "sl_pips": 0.07},
    {"tp_type": "fixed", "tp_pips": 0.20, "sl_type": "fixed", "sl_pips": 0.10},
    {"tp_type": "fixed", "tp_pips": 0.15, "sl_type": "fixed", "sl_pips": 0.15},
]

SESSIONS = [
    [{"type": "session_filter", "session": "london"}],
    [{"type": "session_filter", "session": "newyork"}],
]

FILTERS = [
    [],
    [{"type": "atr_low_vola_filter", "lookback": 60}],
    [{"type": "atr_low_vola_filter", "lookback": 120}],
]

# トレーリングストップ (利益を伸ばす)
TRAIL = [
    {},
    {"trailing": True, "trail_type": "atr_mult", "trail_atr_mult": 0.7},
    {"trailing": True, "trail_type": "atr_mult", "trail_atr_mult": 1.0},
    {"trailing": True, "trail_type": "atr_mult", "trail_atr_mult": 1.5},
    {"trailing": True, "trail_type": "fixed", "trail_distance": 0.03},
    {"trailing": True, "trail_type": "fixed", "trail_distance": 0.05},
]

MAX_BARS = [{}, {"max_bars": 30}, {"max_bars": 60}, {"max_bars": 120}]
BE = [{}, {"breakeven": True, "be_trigger_pips": 0.03}, {"breakeven": True, "be_trigger_pips": 0.05}]
ATR_P = [7, 10, 14]


def _gen(target=300):
    random.seed(31337)
    cfgs, seen = [], set()
    att = 0
    while len(cfgs) < target and att < target * 30:
        att += 1
        sig = random.choice(SIGNALS)
        tpsl = random.choice(TPSL)
        sess = random.choice(SESSIONS)
        filt = random.choice(FILTERS)
        trail = random.choice(TRAIL)
        mb = random.choice(MAX_BARS)
        be = random.choice(BE)
        atr = random.choice(ATR_P)
        ex = {**tpsl, "atr_period": atr, **mb, **be, **trail}
        cfg = {"entry_signal": dict(sig), "entry_filters": sess + filt, "exit_rules": ex}
        cfg["name"] = _make_name(cfg)
        h = hashlib.md5(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()
        if h not in seen:
            seen.add(h); cfgs.append(cfg)
    return cfgs


def _info(c):
    s = c["entry_signal"]; r = c["exit_rules"]; fs = c.get("entry_filters", [])
    tp = f"{r.get('tp_pips',0)*100:.0f}p" if r.get("tp_type")=="fixed" else f"A×{r.get('tp_atr_mult',0)}"
    sl = f"{r.get('sl_pips',0)*100:.0f}p" if r.get("sl_type")=="fixed" else f"A×{r.get('sl_atr_mult',0)}"
    sess = "all"
    lv = False
    for f in fs:
        if f.get("type")=="session_filter": sess=f.get("session","all")
        if f.get("type")=="atr_low_vola_filter": lv=True
    return {"sig_type": s["type"], "cat": s.get("category","?"), "tp_d": tp, "sl_d": sl,
            "sess": sess, "lv": lv, "be": bool(r.get("breakeven")),
            "trail": bool(r.get("trailing")), "trail_type": r.get("trail_type",""),
            "mb": r.get("max_bars",0)}


def _bt(cfgs, dfs, bal, sp, cm, isr=0.7):
    res = []
    tot = len(cfgs)*len(dfs)
    with tqdm(total=tot, desc="  Phase2 OOS") as pb:
        for d in dfs:
            sym, tf = d["symbol"], d["timeframe"]
            try:
                df = load_ohlc(d["filepath"]); _, oos = split_is_oos(df, is_ratio=isr)
            except: pb.update(len(cfgs)); continue
            for c in cfgs:
                try:
                    st = ConfigurableStrategy(config=c, spread=sp, commission=cm)
                    tr = st.backtest(oos, initial_balance=bal)
                    r = evaluate_strategy(tr, bal)
                    r["name"]=c["name"]; r["sym"]=sym; r["tf"]=tf
                    r.update(_info(c))
                    r["hold_m"]=round(r["avg_holding_seconds"]/60,1)
                    if tr:
                        sp_,sc_={k:0.0 for k in["tokyo","london","newyork"]},{k:0 for k in["tokyo","london","newyork"]}
                        for t in tr: s=_classify_session(t.entry_time.hour); sp_[s]+=t.pnl; sc_[s]+=1
                        for k in sp_: r[f"pnl_{k}"]=round(sp_[k],2); r[f"tr_{k}"]=sc_[k]
                    else:
                        for k in["tokyo","london","newyork"]: r[f"pnl_{k}"]=0.0; r[f"tr_{k}"]=0
                    res.append(r)
                except Exception as e: logger.error(f"ERR {c['name']}: {e}")
                finally: pb.update(1)
    return res


def _ss(cfgs, dfs, bal, isr=0.7):
    rows=[]
    tot=len(cfgs)*len(dfs)*len(SPREAD_TESTS)
    with tqdm(total=tot, desc="  Spread感応度") as pb:
        for d in dfs:
            try: df=load_ohlc(d["filepath"]); _,oos=split_is_oos(df,is_ratio=isr)
            except: pb.update(len(cfgs)*len(SPREAD_TESTS)); continue
            for c in cfgs:
                for sp in SPREAD_TESTS:
                    try:
                        st=ConfigurableStrategy(config=c,spread=sp,commission=ECN_COMM)
                        tr=st.backtest(oos,initial_balance=bal); r=evaluate_strategy(tr,bal)
                        rows.append({"name":c["name"],"sym":d["symbol"],"sp":sp*100,
                                     "pf":r["pf"],"tc":r["trade_count"],"st":c["entry_signal"]["type"]})
                    except: pass
                    finally: pb.update(1)
    return rows


def _cap(v,c=10.0):
    if v==float("inf") or v!=v: return c
    return min(v,c)


def run_phase2(settings):
    bal=settings.get("initial_balance",100000)
    ecn=settings.get("ecn",{})
    sp=ecn.get("spread",ECN_SPREAD); cm=ecn.get("commission",ECN_COMM)
    dd=settings.get("data_dir","data/raw"); rd=settings.get("results_dir","results")
    isr=settings.get("research",{}).get("is_ratio",0.7)
    rkd=os.path.join(rd,"ranked"); os.makedirs(rkd,exist_ok=True)

    cost=(sp+cm*2)*100
    print(f"\n{'='*70}")
    print(f"  有望シグナル集中探索 Phase 2")
    print(f"{'='*70}")
    print(f"  ECN: {cost:.1f}pips/trade")
    print(f"  目標: 平均PF≥1.0  最大PF 1.3〜1.5")

    alld=discover_data_files(dd)
    dfs=[d for d in alld if d["symbol"] in SYMBOLS and d["timeframe"]==TF]
    if not dfs: print("  データなし"); return

    # Phase 1: 生成
    cfgs=_gen(target=300)
    print(f"\n  生成: {len(cfgs)} 戦略")
    sd=Counter(c["entry_signal"]["type"] for c in cfgs)
    print(f"  分布: {dict(sd)}")

    # Phase 2: OOS
    print(f"\n  OOS ({len(cfgs)}×{len(dfs)}={len(cfgs)*len(dfs)}テスト)")
    res=_bt(cfgs,dfs,bal,sp,cm,isr)
    print(f"  結果: {len(res)}")
    if not res: return

    df=pd.DataFrame(res)
    df.to_csv(os.path.join(rd,"phase2_all.csv"),index=False,encoding="utf-8-sig")

    # Phase 3: 候補
    fin=np.isfinite(df["pf"])
    expl=df[fin&(df["pf"]>=1.00)&(df["max_dd_pct"]<=20)&(df["trade_count"]>=100)].sort_values("pf",ascending=False).reset_index(drop=True)
    strong=df[fin&(df["pf"]>=1.10)&(df["max_dd_pct"]<=15)&(df["trade_count"]>=200)].sort_values("pf",ascending=False).reset_index(drop=True)
    elite=df[fin&(df["pf"]>=1.20)&(df["trade_count"]>=100)].sort_values("pf",ascending=False).reset_index(drop=True)

    print(f"\n  PF≥1.00 (trades≥100): {len(expl)}")
    print(f"  PF≥1.10 (trades≥200): {len(strong)}")
    print(f"  PF≥1.20 (trades≥100): {len(elite)}")

    expl.to_csv(os.path.join(rkd,"phase2_candidates.csv"),index=False,encoding="utf-8-sig")

    if not expl.empty:
        print(f"\n  {'='*70}")
        print(f"  PF≥1.0 候補 TOP30")
        print(f"  {'='*70}")
        for i,(_,r) in enumerate(expl.head(30).iterrows(),1):
            tags=[]
            if r.get("lv"): tags.append("LV")
            if r.get("be"): tags.append("BE")
            if r.get("trail"): tags.append(f"TR({r.get('trail_type','')})")
            if r.get("mb",0)>0: tags.append(f"{r['mb']}m")
            t=" ".join(tags) if tags else "--"
            print(f"    {i:2d}. {r['sym']}_M1 [{r['sess']:8s}]  PF={r['pf']:.3f}  WR={r['winrate']:.1f}%  DD={r['max_dd_pct']:.1f}%  trades={r['trade_count']:.0f}  hold={r['hold_m']:.0f}m  {r['sig_type']:20s} TP={r['tp_d']:8s} SL={r['sl_d']:8s}  [{t}]")

    if not strong.empty:
        print(f"\n  --- Strong候補 (PF≥1.10, trades≥200) ---")
        for i,(_,r) in enumerate(strong.head(15).iterrows(),1):
            print(f"    {i:2d}. {r['sym']}_M1 [{r['sess']:8s}]  PF={r['pf']:.3f}  WR={r['winrate']:.1f}%  trades={r['trade_count']:.0f}  {r['sig_type']:20s} TP={r['tp_d']} SL={r['sl_d']}")

    if not elite.empty:
        print(f"\n  --- Elite候補 (PF≥1.20) ---")
        for i,(_,r) in enumerate(elite.head(10).iterrows(),1):
            print(f"    {i:2d}. {r['sym']}_M1  PF={r['pf']:.3f}  WR={r['winrate']:.1f}%  trades={r['trade_count']:.0f}  {r['sig_type']}")

    # Phase 4: Spread sensitivity
    print(f"\n  Phase 4: Spread感応度")
    if not expl.empty:
        tn=set(expl["name"].unique())
    else:
        tn=set(df.nlargest(50,"pf")["name"].unique())
    sc=[c for c in cfgs if c["name"] in tn]
    print(f"  対象: {len(sc)} 戦略")
    sr=_ss(sc,dfs,bal,isr)
    if sr:
        sdf=pd.DataFrame(sr); sdf["pfc"]=sdf["pf"].apply(_cap)
        pv=sdf.groupby(["name","sp"]).agg(pf=("pfc","mean"),tc=("tc","mean")).reset_index()
        pw=pv.pivot(index="name",columns="sp",values="pf")
        pw.columns=[f"sp{c:.1f}" for c in pw.columns]; pw=pw.reset_index()
        sp05="sp0.5"
        if sp05 in pw.columns:
            pw["robust"]=pw[sp05]>=1.00
            nr=pw["robust"].sum()
            print(f"  robust (sp=0.5でPF≥1.0): {nr}")
        pw.sort_values(sp05 if sp05 in pw.columns else pw.columns[1],ascending=False).to_csv(
            os.path.join(rkd,"phase2_spread_robust.csv"),index=False,encoding="utf-8-sig")
        print(f"\n  --- Spread耐性 TOP15 ---")
        for _,r in pw.sort_values(sp05 if sp05 in pw.columns else pw.columns[1],ascending=False).head(15).iterrows():
            cols=[c for c in pw.columns if c.startswith("sp")]
            v="  ".join(f"{c}={r[c]:.3f}" for c in cols)
            rob="ROBUST" if r.get("robust",False) else ""
            print(f"    {r['name'][:35]:35s}  {v}  {rob}")

    # Phase 5: 分析
    print(f"\n{'='*70}")
    print(f"  分析")
    print(f"{'='*70}")
    st=df[df["trade_count"]>=50].copy(); st["pf"]=st["pf"].apply(_cap)
    if not st.empty:
        # シグナル別
        print(f"\n  --- シグナル別 ---")
        sg=st.groupby("sig_type").agg(
            avg=("pf","mean"),med=("pf","median"),mx=("pf","max"),
            wr=("winrate","mean"),tc=("trade_count","mean"),hd=("hold_m","mean"),
            n=("pf","count"),ok=("pf",lambda x:(x>=1.0).sum()),
        ).sort_values("avg",ascending=False)
        for i,r in sg.iterrows():
            print(f"    {i:25s}  avgPF={r['avg']:.3f}  medPF={r['med']:.3f}  maxPF={r['mx']:.3f}  WR={r['wr']:.1f}%  trades={r['tc']:.0f}  hold={r['hd']:.0f}m  PF≥1.0={r['ok']:.0f}/{r['n']:.0f}")

        # 通貨
        print(f"\n  --- 通貨別 ---")
        for i,r in st.groupby("sym").agg(avg=("pf","mean"),mx=("pf","max"),ok=("pf",lambda x:(x>=1.0).sum())).sort_values("avg",ascending=False).iterrows():
            print(f"    {i:10s}  avgPF={r['avg']:.3f}  maxPF={r['mx']:.3f}  PF≥1.0={r['ok']:.0f}")

        # TP/SL
        print(f"\n  --- TP/SL別 ---")
        st["tpsl"]=st["tp_d"]+"/"+st["sl_d"]
        for i,r in st.groupby("tpsl").agg(avg=("pf","mean"),mx=("pf","max"),n=("pf","count"),ok=("pf",lambda x:(x>=1.0).sum())).sort_values("avg",ascending=False).head(10).iterrows():
            print(f"    {i:20s}  avgPF={r['avg']:.3f}  maxPF={r['mx']:.3f}  PF≥1.0={r['ok']:.0f}/{r['n']:.0f}")

        # トレーリング
        print(f"\n  --- トレーリング効果 ---")
        for i,r in st.groupby("trail").agg(avg=("pf","mean"),med=("pf","median"),tc=("trade_count","mean")).iterrows():
            print(f"    trail={'あり' if i else 'なし'}  avgPF={r['avg']:.3f}  medPF={r['med']:.3f}  trades={r['tc']:.0f}")

        # セッション
        print(f"\n  --- セッション別 ---")
        for i,r in st.groupby("sess").agg(avg=("pf","mean"),ok=("pf",lambda x:(x>=1.0).sum())).sort_values("avg",ascending=False).iterrows():
            print(f"    {i:10s}  avgPF={r['avg']:.3f}  PF≥1.0={r['ok']:.0f}")

    ne=len(expl); ns=len(strong); nel=len(elite)
    print(f"\n{'='*70}")
    print(f"  結論: exploration={ne}  strong={ns}  elite={nel}")
    if nel>0: print(f"  PF≥1.2のエリート戦略発見！！")
    elif ns>0: print(f"  PF≥1.1のstrong戦略あり！")
    elif ne>0: print(f"  PF≥1.0候補あり。さらに最適化の余地。")
    else: print(f"  まだPF<1.0。パラメータ調整継続。")
    print(f"{'='*70}")
    print(f"  cd fx_lab && python main.py --phase2")
    print(f"{'='*70}")


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_dir)
    import yaml
    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.FileHandler("logs/phase2.log",encoding="utf-8"),logging.StreamHandler(sys.stdout)])
    with open(os.path.join("config","settings.yaml"),"r",encoding="utf-8") as f: settings=yaml.safe_load(f)
    run_phase2(settings)
