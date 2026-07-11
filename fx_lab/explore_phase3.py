"""Phase 3: atr_break集中砲撃 + walk-forward検証

Phase 2の結果:
  atr_break: avgPF=0.994, maxPF=1.877, PF≥1.0率=39% ← 最強
  hilo_break: maxPF=1.387
  bb_bounce: maxPF=1.374

Phase 3:
  1) atr_break超精密グリッド (200個)
  2) hilo_break/bb_bounce追加 (100個)
  3) 上位候補のwalk-forward検証
  4) パラメータ安定性テスト (近傍パラメータも機能するか)
  5) spread感応度
"""

import os, sys, itertools, hashlib, json, logging, random
from collections import Counter
import pandas as pd, numpy as np
from tqdm import tqdm

from engine.strategy_generator import _make_name
from engine.configurable_strategy import ConfigurableStrategy
from data_loader import load_ohlc, discover_data_files
from metrics import evaluate_strategy
from engine.evolution import split_is_oos, split_walk_forward, _classify_session

logger = logging.getLogger(__name__)

ECN_SP = 0.003; ECN_CM = 0.0025
SP_TESTS = [0.002, 0.003, 0.005, 0.010]
SYMS = ["USDJPY", "EURJPY", "GBPJPY"]; TF = "M1"

# ================================================================
# atr_break 超精密グリッド
# ================================================================
ATR_BREAK_SIGS = []
for p in [5, 7, 8, 10, 12, 14, 16, 20]:
    for m in [0.8, 1.0, 1.2, 1.5, 1.8, 2.0, 2.5]:
        ATR_BREAK_SIGS.append({"type": "atr_break", "category": "breakout", "period": p, "multiplier": m})

HILO_SIGS = []
for lb in [5, 7, 10, 12, 15, 20, 25]:
    for cb in [1, 2]:
        HILO_SIGS.append({"type": "hilo_break", "category": "breakout", "lookback": lb, "confirm_bars": cb})

BB_SIGS = []
for per in [10, 14, 20, 25, 30]:
    for std in [1.5, 2.0, 2.5]:
        BB_SIGS.append({"type": "bb_bounce", "category": "mean_reversion", "period": per, "std_mult": std})

# ATR損小利大TP/SL (前回の勝ちパターン)
TPSL = [
    {"tp_type":"atr_mult","tp_atr_mult":2.0,"sl_type":"atr_mult","sl_atr_mult":0.7},
    {"tp_type":"atr_mult","tp_atr_mult":2.5,"sl_type":"atr_mult","sl_atr_mult":1.0},
    {"tp_type":"atr_mult","tp_atr_mult":3.0,"sl_type":"atr_mult","sl_atr_mult":1.0},
    {"tp_type":"atr_mult","tp_atr_mult":3.0,"sl_type":"atr_mult","sl_atr_mult":1.5},
    {"tp_type":"atr_mult","tp_atr_mult":4.0,"sl_type":"atr_mult","sl_atr_mult":1.0},
    {"tp_type":"atr_mult","tp_atr_mult":4.0,"sl_type":"atr_mult","sl_atr_mult":1.5},
    {"tp_type":"atr_mult","tp_atr_mult":5.0,"sl_type":"atr_mult","sl_atr_mult":1.5},
    {"tp_type":"atr_mult","tp_atr_mult":5.0,"sl_type":"atr_mult","sl_atr_mult":2.0},
    {"tp_type":"atr_mult","tp_atr_mult":6.0,"sl_type":"atr_mult","sl_atr_mult":1.5},
    {"tp_type":"atr_mult","tp_atr_mult":3.0,"sl_type":"atr_mult","sl_atr_mult":0.7},
]

SESS = [[{"type":"session_filter","session":"london"}],[{"type":"session_filter","session":"newyork"}]]
FILT = [[],[{"type":"atr_low_vola_filter","lookback":60}],[{"type":"atr_low_vola_filter","lookback":120}]]
TRAIL = [{},{"trailing":True,"trail_type":"atr_mult","trail_atr_mult":0.7},
         {"trailing":True,"trail_type":"atr_mult","trail_atr_mult":1.0},
         {"trailing":True,"trail_type":"atr_mult","trail_atr_mult":1.5}]
MB = [{},{"max_bars":30},{"max_bars":60},{"max_bars":120}]
BE = [{},{"breakeven":True,"be_trigger_pips":0.03},{"breakeven":True,"be_trigger_pips":0.05}]
ATRP = [7, 10, 14]


def _gen(target=350):
    random.seed(77777)
    cfgs, seen = [], set()
    # Phase A: atr_break集中 (200個)
    while len(cfgs) < min(target * 6 // 10, 200):
        sig = random.choice(ATR_BREAK_SIGS)
        tpsl = random.choice(TPSL); s = random.choice(SESS); f = random.choice(FILT)
        tr = random.choice(TRAIL); mb = random.choice(MB); be = random.choice(BE); ap = random.choice(ATRP)
        cfg = {"entry_signal":dict(sig),"entry_filters":s+f,"exit_rules":{**tpsl,"atr_period":ap,**mb,**be,**tr}}
        cfg["name"] = _make_name(cfg)
        h = hashlib.md5(json.dumps(cfg,sort_keys=True,default=str).encode()).hexdigest()
        if h not in seen: seen.add(h); cfgs.append(cfg)
    # Phase B: hilo_break (80個)
    while len(cfgs) < min(target * 83 // 100, 280):
        sig = random.choice(HILO_SIGS)
        tpsl = random.choice(TPSL); s = random.choice(SESS); f = random.choice(FILT)
        tr = random.choice(TRAIL); mb = random.choice(MB); be = random.choice(BE); ap = random.choice(ATRP)
        cfg = {"entry_signal":dict(sig),"entry_filters":s+f,"exit_rules":{**tpsl,"atr_period":ap,**mb,**be,**tr}}
        cfg["name"] = _make_name(cfg)
        h = hashlib.md5(json.dumps(cfg,sort_keys=True,default=str).encode()).hexdigest()
        if h not in seen: seen.add(h); cfgs.append(cfg)
    # Phase C: bb_bounce (70個)
    while len(cfgs) < target:
        sig = random.choice(BB_SIGS)
        tpsl = random.choice(TPSL); s = random.choice(SESS); f = random.choice(FILT)
        tr = random.choice(TRAIL); mb = random.choice(MB); be = random.choice(BE); ap = random.choice(ATRP)
        cfg = {"entry_signal":dict(sig),"entry_filters":s+f,"exit_rules":{**tpsl,"atr_period":ap,**mb,**be,**tr}}
        cfg["name"] = _make_name(cfg)
        h = hashlib.md5(json.dumps(cfg,sort_keys=True,default=str).encode()).hexdigest()
        if h not in seen: seen.add(h); cfgs.append(cfg)
    return cfgs


def _info(c):
    s=c["entry_signal"]; r=c["exit_rules"]; fs=c.get("entry_filters",[])
    tp=f"A×{r.get('tp_atr_mult',0)}" if r.get("tp_type")=="atr_mult" else f"{r.get('tp_pips',0)*100:.0f}p"
    sl=f"A×{r.get('sl_atr_mult',0)}" if r.get("sl_type")=="atr_mult" else f"{r.get('sl_pips',0)*100:.0f}p"
    sess="all"; lv=False
    for f in fs:
        if f.get("type")=="session_filter": sess=f.get("session","all")
        if f.get("type")=="atr_low_vola_filter": lv=True
    extra = {}
    if s["type"]=="atr_break": extra={"ab_period":s.get("period",0),"ab_mult":s.get("multiplier",0)}
    elif s["type"]=="hilo_break": extra={"hl_lb":s.get("lookback",0),"hl_cb":s.get("confirm_bars",0)}
    elif s["type"]=="bb_bounce": extra={"bb_p":s.get("period",0),"bb_std":s.get("std_mult",0)}
    return {"sig":s["type"],"tp":tp,"sl":sl,"sess":sess,"lv":lv,
            "be":bool(r.get("breakeven")),"trail":bool(r.get("trailing")),
            "mb":r.get("max_bars",0),**extra}


def _bt(cfgs, dfs, bal, sp, cm, isr=0.7):
    res=[]; tot=len(cfgs)*len(dfs)
    with tqdm(total=tot, desc="  OOS") as pb:
        for d in dfs:
            sym=d["symbol"]
            try: df=load_ohlc(d["filepath"]); _,oos=split_is_oos(df,is_ratio=isr)
            except: pb.update(len(cfgs)); continue
            for c in cfgs:
                try:
                    st=ConfigurableStrategy(config=c,spread=sp,commission=cm)
                    tr=st.backtest(oos,initial_balance=bal); r=evaluate_strategy(tr,bal)
                    r["name"]=c["name"]; r["sym"]=sym
                    r.update(_info(c))
                    r["hold_m"]=round(r["avg_holding_seconds"]/60,1)
                    res.append(r)
                except: pass
                finally: pb.update(1)
    return res


def _wf(cfgs, dfs, bal, sp, cm, n_win=4, isr=0.7):
    """Walk-forward検証"""
    results = []
    for d in dfs:
        sym = d["symbol"]
        try: df = load_ohlc(d["filepath"])
        except: continue
        windows = split_walk_forward(df, n_windows=n_win, is_ratio=isr)
        for c in cfgs:
            is_pfs, oos_pfs = [], []
            for is_df, oos_df in windows:
                try:
                    st = ConfigurableStrategy(config=c, spread=sp, commission=cm)
                    is_tr = st.backtest(is_df, initial_balance=bal)
                    is_m = evaluate_strategy(is_tr, bal)
                    is_pfs.append(is_m["pf"] if np.isfinite(is_m["pf"]) else 0)
                    st2 = ConfigurableStrategy(config=c, spread=sp, commission=cm)
                    oos_tr = st2.backtest(oos_df, initial_balance=bal)
                    oos_m = evaluate_strategy(oos_tr, bal)
                    oos_pfs.append(oos_m["pf"] if np.isfinite(oos_m["pf"]) else 0)
                except: pass
            if is_pfs and oos_pfs:
                avg_is = np.mean([min(p,10) for p in is_pfs])
                avg_oos = np.mean([min(p,10) for p in oos_pfs])
                ratio = avg_oos / avg_is if avg_is > 0 else 0
                results.append({"name": c["name"], "sym": sym, "sig": c["entry_signal"]["type"],
                                "is_pf": round(avg_is,3), "oos_pf": round(avg_oos,3),
                                "oos_is": round(ratio,3), "windows": len(is_pfs)})
    return results


def _cap(v): return min(v,10) if np.isfinite(v) else 10.0


def run_phase3(settings):
    bal=settings.get("initial_balance",100000)
    ecn=settings.get("ecn",{}); sp=ecn.get("spread",ECN_SP); cm=ecn.get("commission",ECN_CM)
    dd=settings.get("data_dir","data/raw"); rd=settings.get("results_dir","results")
    isr=settings.get("research",{}).get("is_ratio",0.7)
    rkd=os.path.join(rd,"ranked"); os.makedirs(rkd,exist_ok=True)

    print(f"\n{'='*70}")
    print(f"  Phase 3: atr_break集中砲撃 + walk-forward検証")
    print(f"{'='*70}")

    alld=discover_data_files(dd)
    dfs=[d for d in alld if d["symbol"] in SYMS and d["timeframe"]==TF]
    if not dfs: return

    # === 1. 生成 ===
    cfgs=_gen(350)
    sd=Counter(c["entry_signal"]["type"] for c in cfgs)
    print(f"  生成: {len(cfgs)} ({dict(sd)})")

    # === 2. OOS ===
    print(f"\n  OOS ({len(cfgs)}×{len(dfs)}={len(cfgs)*len(dfs)}テスト)")
    res=_bt(cfgs,dfs,bal,sp,cm,isr)
    print(f"  結果: {len(res)}")
    if not res: return

    df=pd.DataFrame(res)
    df.to_csv(os.path.join(rd,"phase3_all.csv"),index=False,encoding="utf-8-sig")

    # === 3. 候補 ===
    fin=np.isfinite(df["pf"])
    expl=df[fin&(df["pf"]>=1.00)&(df["trade_count"]>=50)].sort_values("pf",ascending=False).reset_index(drop=True)
    strong=df[fin&(df["pf"]>=1.10)&(df["trade_count"]>=100)].sort_values("pf",ascending=False).reset_index(drop=True)
    elite=df[fin&(df["pf"]>=1.20)&(df["trade_count"]>=50)].sort_values("pf",ascending=False).reset_index(drop=True)

    print(f"\n  PF≥1.00 (tr≥50):  {len(expl)}")
    print(f"  PF≥1.10 (tr≥100): {len(strong)}")
    print(f"  PF≥1.20 (tr≥50):  {len(elite)}")

    expl.to_csv(os.path.join(rkd,"phase3_candidates.csv"),index=False,encoding="utf-8-sig")

    if not expl.empty:
        print(f"\n  --- PF≥1.0 TOP30 ---")
        for i,(_,r) in enumerate(expl.head(30).iterrows(),1):
            tags=[]
            if r.get("lv"): tags.append("LV")
            if r.get("be"): tags.append("BE")
            if r.get("trail"): tags.append("TR")
            if r.get("mb",0)>0: tags.append(f"{r['mb']}m")
            t=" ".join(tags) if tags else "--"
            extra=""
            if r["sig"]=="atr_break": extra=f"  per={r.get('ab_period','')} mult={r.get('ab_mult','')}"
            elif r["sig"]=="hilo_break": extra=f"  lb={r.get('hl_lb','')} cb={r.get('hl_cb','')}"
            elif r["sig"]=="bb_bounce": extra=f"  p={r.get('bb_p','')} std={r.get('bb_std','')}"
            print(f"    {i:2d}. {r['sym']}_M1 [{r['sess']:8s}]  PF={r['pf']:.3f}  WR={r['winrate']:.1f}%  trades={r['trade_count']:.0f}  hold={r['hold_m']:.0f}m  {r['sig']:15s} TP={r['tp']:8s} SL={r['sl']:8s} [{t}]{extra}")

    # === 4. Walk-Forward検証 (上位戦略) ===
    print(f"\n  === Walk-Forward検証 ===")
    if not expl.empty:
        wf_names = set(expl.head(40)["name"].unique())
    else:
        wf_names = set(df.nlargest(40,"pf")["name"].unique())
    wf_cfgs = [c for c in cfgs if c["name"] in wf_names]
    print(f"  対象: {len(wf_cfgs)} 戦略 × {len(dfs)} 通貨 × 4窓")

    wf_res = _wf(wf_cfgs, dfs, bal, sp, cm, n_win=4, isr=isr)
    if wf_res:
        wdf = pd.DataFrame(wf_res)
        wdf.to_csv(os.path.join(rd,"phase3_walkforward.csv"),index=False,encoding="utf-8-sig")

        # OOS/IS比率で安定性を評価
        wf_agg = wdf.groupby("name").agg(
            avg_is=("is_pf","mean"), avg_oos=("oos_pf","mean"),
            avg_ratio=("oos_is","mean"), sig=("sig","first"),
        ).sort_values("avg_oos", ascending=False)

        print(f"\n  --- Walk-Forward結果 TOP20 ---")
        print(f"  {'name':35s}  {'sig':15s}  IS_PF   OOS_PF  OOS/IS  判定")
        for nm, r in wf_agg.head(20).iterrows():
            ratio = r["avg_ratio"]
            if ratio >= 0.8 and r["avg_oos"] >= 1.0:
                judge = "★★★ 安定"
            elif ratio >= 0.6 and r["avg_oos"] >= 0.9:
                judge = "★★  有望"
            elif ratio >= 0.5:
                judge = "★   要注意"
            else:
                judge = "×   過学習疑い"
            print(f"    {nm[:35]:35s}  {r['sig']:15s}  {r['avg_is']:.3f}   {r['avg_oos']:.3f}   {ratio:.2f}    {judge}")

        # 安定戦略カウント
        stable = wf_agg[(wf_agg["avg_oos"] >= 1.0) & (wf_agg["avg_ratio"] >= 0.7)]
        print(f"\n  安定戦略 (OOS_PF≥1.0 & OOS/IS≥0.7): {len(stable)}")
        if not stable.empty:
            for nm, r in stable.iterrows():
                print(f"    {nm[:40]:40s}  OOS_PF={r['avg_oos']:.3f}  OOS/IS={r['avg_ratio']:.2f}  {r['sig']}")

    # === 5. Spread感応度 ===
    print(f"\n  === Spread感応度 ===")
    if not expl.empty:
        sn = set(expl.head(30)["name"].unique())
    else:
        sn = set(df.nlargest(30,"pf")["name"].unique())
    sc = [c for c in cfgs if c["name"] in sn]
    sr = []
    tot = len(sc)*len(dfs)*len(SP_TESTS)
    with tqdm(total=tot, desc="  Spread") as pb:
        for d in dfs:
            try: odf=load_ohlc(d["filepath"]); _,oos=split_is_oos(odf,is_ratio=isr)
            except: pb.update(len(sc)*len(SP_TESTS)); continue
            for c in sc:
                for spv in SP_TESTS:
                    try:
                        st=ConfigurableStrategy(config=c,spread=spv,commission=ECN_CM)
                        tr=st.backtest(oos,initial_balance=bal); r=evaluate_strategy(tr,bal)
                        sr.append({"name":c["name"],"sp":spv*100,"pf":_cap(r["pf"]),"tc":r["trade_count"]})
                    except: pass
                    finally: pb.update(1)
    if sr:
        sdf=pd.DataFrame(sr)
        pv=sdf.groupby(["name","sp"])["pf"].mean().reset_index()
        pw=pv.pivot(index="name",columns="sp",values="pf")
        pw.columns=[f"sp{c:.1f}" for c in pw.columns]; pw=pw.reset_index()
        if "sp0.5" in pw.columns:
            pw["robust"]=pw["sp0.5"]>=1.00
            nr=pw["robust"].sum()
            print(f"\n  robust (sp=0.5でPF≥1.0): {nr}")
        pw.sort_values("sp0.5" if "sp0.5" in pw.columns else pw.columns[1],ascending=False).to_csv(
            os.path.join(rkd,"phase3_spread.csv"),index=False,encoding="utf-8-sig")

        print(f"\n  --- Spread耐性 TOP15 ---")
        for _,r in pw.sort_values("sp0.5" if "sp0.5" in pw.columns else pw.columns[1],ascending=False).head(15).iterrows():
            cols=[c for c in pw.columns if c.startswith("sp")]
            v="  ".join(f"{c}={r[c]:.3f}" for c in cols)
            rob="ROBUST" if r.get("robust",False) else ""
            print(f"    {r['name'][:35]:35s}  {v}  {rob}")

    # === 6. 分析 ===
    print(f"\n{'='*70}")
    print(f"  Phase 3 分析")
    print(f"{'='*70}")
    st=df[df["trade_count"]>=30].copy(); st["pf"]=st["pf"].apply(_cap)

    if not st.empty:
        # シグナル別
        print(f"\n  --- シグナル別 ---")
        for i,r in st.groupby("sig").agg(avg=("pf","mean"),med=("pf","median"),mx=("pf","max"),
            wr=("winrate","mean"),tc=("trade_count","mean"),n=("pf","count"),
            ok=("pf",lambda x:(x>=1.0).sum())).sort_values("avg",ascending=False).iterrows():
            print(f"    {i:15s}  avg={r['avg']:.3f}  med={r['med']:.3f}  max={r['mx']:.3f}  WR={r['wr']:.1f}%  trades={r['tc']:.0f}  PF≥1.0={r['ok']:.0f}/{r['n']:.0f} ({r['ok']/r['n']*100:.0f}%)")

        # atr_break精密分析
        ab=st[st["sig"]=="atr_break"]
        if not ab.empty and "ab_period" in ab.columns and "ab_mult" in ab.columns:
            print(f"\n  --- atr_break: period × multiplier ヒートマップ ---")
            hm=ab.groupby(["ab_period","ab_mult"])["pf"].mean().reset_index()
            hm_pv=hm.pivot(index="ab_period",columns="ab_mult",values="pf")
            print(f"    {'period':>6s}", end="")
            for c in hm_pv.columns: print(f"  m={c:.1f}", end="")
            print()
            for idx, row in hm_pv.iterrows():
                print(f"    {idx:6.0f}", end="")
                for v in row.values:
                    marker = "★" if v >= 1.0 else " "
                    print(f"  {v:.3f}{marker}", end="")
                print()

        # 通貨別
        print(f"\n  --- 通貨別 ---")
        for i,r in st.groupby("sym").agg(avg=("pf","mean"),mx=("pf","max"),ok=("pf",lambda x:(x>=1.0).sum())).sort_values("avg",ascending=False).iterrows():
            print(f"    {i:10s}  avg={r['avg']:.3f}  max={r['mx']:.3f}  PF≥1.0={r['ok']:.0f}")

        # TP/SL
        print(f"\n  --- TP/SL別 ---")
        st["tpsl"]=st["tp"]+"/"+st["sl"]
        for i,r in st.groupby("tpsl").agg(avg=("pf","mean"),mx=("pf","max"),n=("pf","count"),ok=("pf",lambda x:(x>=1.0).sum())).sort_values("avg",ascending=False).head(10).iterrows():
            print(f"    {i:20s}  avg={r['avg']:.3f}  max={r['mx']:.3f}  PF≥1.0={r['ok']:.0f}/{r['n']:.0f}")

    # 結論
    ne=len(expl); ns=len(strong); nel=len(elite)
    print(f"\n{'='*70}")
    print(f"  結論")
    print(f"{'='*70}")
    print(f"  exploration={ne}  strong={ns}  elite={nel}")
    if nel>=5: print(f"  エリート5個以上！ walk-forward安定ならEA化検討。")
    elif nel>0: print(f"  エリート発見。パラメータ安定性を確認中。")
    print(f"  cd fx_lab && python main.py --phase3")
    print(f"{'='*70}")


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_dir)
    import yaml; os.makedirs("logs",exist_ok=True)
    logging.basicConfig(level=logging.INFO,format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.FileHandler("logs/phase3.log",encoding="utf-8"),logging.StreamHandler(sys.stdout)])
    with open(os.path.join("config","settings.yaml"),"r",encoding="utf-8") as f: settings=yaml.safe_load(f)
    run_phase3(settings)
