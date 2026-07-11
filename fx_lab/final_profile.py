"""最終候補プロファイル + MT4 EA生成

Phase3で3つの関門を突破した戦略の詳細分析:
  1. エクイティカーブ (累積PNL推移)
  2. 月次PNLテーブル
  3. トレード統計 (勝ち/負け分布, 最大連敗, 保有時間分布)
  4. 通貨別パフォーマンス
  5. MT4 EA (MQL4) コード生成
"""

import os, sys, json, logging
import pandas as pd, numpy as np

from engine.strategy_generator import _make_name
from engine.configurable_strategy import ConfigurableStrategy
from data_loader import load_ohlc, discover_data_files
from metrics import evaluate_strategy
from engine.evolution import split_is_oos, split_walk_forward, _classify_session

logger = logging.getLogger(__name__)

ECN_SP = 0.003; ECN_CM = 0.0025
SYMS = ["USDJPY","EURJPY","GBPJPY"]; TF = "M1"

# ================================================================
# 最終候補5戦略 (WF安定 + spread robust + 高PF)
# ================================================================
FINAL_CONFIGS = [
    # 1. atr_break_399687a7: WF OOS=1.085, sp0.5=1.189 ROBUST, PF=1.552
    {
        "entry_signal": {"type":"atr_break","category":"breakout","period":5,"multiplier":1.0},
        "entry_filters": [{"type":"session_filter","session":"newyork"},{"type":"atr_low_vola_filter","lookback":60}],
        "exit_rules": {"tp_type":"atr_mult","tp_atr_mult":4.0,"sl_type":"atr_mult","sl_atr_mult":1.5,
                       "atr_period":10,"breakeven":True,"be_trigger_pips":0.03,
                       "trailing":True,"trail_type":"atr_mult","trail_atr_mult":0.7},
        "name": "atr_break_399687a7",
        "label": "ATR Break P5M1.0 NY LV BE TR",
    },
    # 2. atr_break_50bd79db: WF OOS=1.133, sp0.5=1.123 ROBUST, PF=1.522
    {
        "entry_signal": {"type":"atr_break","category":"breakout","period":5,"multiplier":1.0},
        "entry_filters": [{"type":"session_filter","session":"newyork"},{"type":"atr_low_vola_filter","lookback":60}],
        "exit_rules": {"tp_type":"atr_mult","tp_atr_mult":6.0,"sl_type":"atr_mult","sl_atr_mult":1.5,
                       "atr_period":10,"breakeven":True,"be_trigger_pips":0.03,"max_bars":120,
                       "trailing":True,"trail_type":"atr_mult","trail_atr_mult":0.7},
        "name": "atr_break_50bd79db",
        "label": "ATR Break P5M1.0 NY LV BE TR 120m",
    },
    # 3. hilo_break_00369025: WF OOS=2.256(!), sp0.5=1.098 ROBUST
    {
        "entry_signal": {"type":"hilo_break","category":"breakout","lookback":15,"confirm_bars":1},
        "entry_filters": [{"type":"session_filter","session":"newyork"},{"type":"atr_low_vola_filter","lookback":120}],
        "exit_rules": {"tp_type":"atr_mult","tp_atr_mult":5.0,"sl_type":"atr_mult","sl_atr_mult":1.5,
                       "atr_period":14,"max_bars":120},
        "name": "hilo_break_00369025",
        "label": "HiLo Break LB15 NY LV 120m",
    },
    # 4. hilo_break_80ddd660: WF OOS=1.700, sp0.5=1.091 ROBUST
    {
        "entry_signal": {"type":"hilo_break","category":"breakout","lookback":5,"confirm_bars":2},
        "entry_filters": [{"type":"session_filter","session":"london"}],
        "exit_rules": {"tp_type":"atr_mult","tp_atr_mult":3.0,"sl_type":"atr_mult","sl_atr_mult":1.0,
                       "atr_period":14,"breakeven":True,"be_trigger_pips":0.05,
                       "trailing":True,"trail_type":"atr_mult","trail_atr_mult":1.0,"max_bars":60},
        "name": "hilo_break_80ddd660",
        "label": "HiLo Break LB5CB2 LN BE TR 60m",
    },
    # 5. atr_break_d0675dfa: sp0.5=1.112, sp1.0=1.065 最高spread耐性
    {
        "entry_signal": {"type":"atr_break","category":"breakout","period":10,"multiplier":0.8},
        "entry_filters": [{"type":"session_filter","session":"newyork"},{"type":"atr_low_vola_filter","lookback":120}],
        "exit_rules": {"tp_type":"atr_mult","tp_atr_mult":3.0,"sl_type":"atr_mult","sl_atr_mult":1.5,
                       "atr_period":14,"trailing":True,"trail_type":"atr_mult","trail_atr_mult":1.5,"max_bars":120},
        "name": "atr_break_d0675dfa",
        "label": "ATR Break P10M0.8 NY LV TR 120m",
    },
]


def _profile_strategy(cfg, data_files, bal, sp, cm, is_ratio):
    """1戦略の詳細プロファイルを生成"""
    name = cfg["name"]
    label = cfg.get("label", name)
    profile = {"name": name, "label": label, "currencies": {}}

    for di in data_files:
        sym = di["symbol"]
        try:
            df = load_ohlc(di["filepath"])
            _, oos = split_is_oos(df, is_ratio=is_ratio)
        except:
            continue

        strat = ConfigurableStrategy(config=cfg, spread=sp, commission=cm)
        trades = strat.backtest(oos, initial_balance=bal)
        metrics = evaluate_strategy(trades, bal)

        # エクイティカーブ
        equity = [bal]
        for t in trades:
            equity.append(equity[-1] + t.pnl)

        # 月次PNL
        monthly = {}
        for t in trades:
            key = t.entry_time.strftime("%Y-%m")
            monthly[key] = monthly.get(key, 0) + t.pnl

        # 勝ち/負け統計
        wins = [t.pnl for t in trades if t.pnl > 0]
        losses = [t.pnl for t in trades if t.pnl <= 0]
        holds = [t.holding_seconds / 60 for t in trades]  # 分

        # セッション別
        sess_pnl = {"tokyo": 0, "london": 0, "newyork": 0}
        sess_cnt = {"tokyo": 0, "london": 0, "newyork": 0}
        for t in trades:
            s = _classify_session(t.entry_time.hour)
            sess_pnl[s] += t.pnl; sess_cnt[s] += 1

        # Long/Short別
        long_pnl = sum(t.pnl for t in trades if t.direction == "long")
        short_pnl = sum(t.pnl for t in trades if t.direction == "short")
        long_cnt = sum(1 for t in trades if t.direction == "long")
        short_cnt = sum(1 for t in trades if t.direction == "short")

        profile["currencies"][sym] = {
            "metrics": metrics,
            "equity": equity,
            "monthly": monthly,
            "wins": wins, "losses": losses, "holds": holds,
            "sess_pnl": sess_pnl, "sess_cnt": sess_cnt,
            "long_pnl": long_pnl, "short_pnl": short_pnl,
            "long_cnt": long_cnt, "short_cnt": short_cnt,
        }

    # Walk-forward
    wf_results = {}
    for di in data_files:
        sym = di["symbol"]
        try:
            df = load_ohlc(di["filepath"])
            windows = split_walk_forward(df, n_windows=4, is_ratio=is_ratio)
        except:
            continue
        is_pfs, oos_pfs = [], []
        for is_df, oos_df in windows:
            try:
                s1 = ConfigurableStrategy(config=cfg, spread=sp, commission=cm)
                is_t = s1.backtest(is_df, initial_balance=bal)
                is_m = evaluate_strategy(is_t, bal)
                is_pfs.append(min(is_m["pf"], 10) if np.isfinite(is_m["pf"]) else 0)
                s2 = ConfigurableStrategy(config=cfg, spread=sp, commission=cm)
                oos_t = s2.backtest(oos_df, initial_balance=bal)
                oos_m = evaluate_strategy(oos_t, bal)
                oos_pfs.append(min(oos_m["pf"], 10) if np.isfinite(oos_m["pf"]) else 0)
            except:
                pass
        if is_pfs:
            wf_results[sym] = {"is_pfs": is_pfs, "oos_pfs": oos_pfs,
                                "avg_is": np.mean(is_pfs), "avg_oos": np.mean(oos_pfs)}
    profile["wf"] = wf_results
    return profile


def _print_profile(p):
    """プロファイルをテキスト出力"""
    print(f"\n{'='*70}")
    print(f"  {p['label']}")
    print(f"  {p['name']}")
    print(f"{'='*70}")

    for sym, d in p["currencies"].items():
        m = d["metrics"]
        print(f"\n  [{sym}_M1]")
        print(f"    PF={m['pf']:.3f}  WR={m['winrate']:.1f}%  trades={m['trade_count']}  DD={m['max_dd_pct']:.1f}%")
        print(f"    PNL={m['total_pnl']:.2f}  期待値={m['expectancy']:.4f}  ペイオフ={m['payoff_ratio']:.3f}")
        print(f"    最大連敗={m['max_consecutive_losses']}  最大連勝={m['max_consecutive_wins']}")
        print(f"    保有: avg={np.mean(d['holds']):.1f}m  med={np.median(d['holds']) if d['holds'] else 0:.1f}m  max={max(d['holds']) if d['holds'] else 0:.0f}m")
        print(f"    Long: {d['long_cnt']}回 PNL={d['long_pnl']:.2f}  Short: {d['short_cnt']}回 PNL={d['short_pnl']:.2f}")

        # セッション
        for s in ["tokyo","london","newyork"]:
            cnt = d["sess_cnt"][s]
            pnl = d["sess_pnl"][s]
            if cnt > 0:
                print(f"    {s:10s}: {cnt:3d}回  PNL={pnl:+.2f}")

        # 月次PNL
        if d["monthly"]:
            print(f"    月次PNL:")
            for mo, pnl in sorted(d["monthly"].items()):
                bar = "+" * max(1, int(abs(pnl) * 10)) if pnl > 0 else "-" * max(1, int(abs(pnl) * 10))
                print(f"      {mo}  {pnl:+8.2f}  {bar}")

        # エクイティカーブ (テキスト簡易表示)
        eq = d["equity"]
        if len(eq) > 1:
            mn, mx = min(eq), max(eq)
            print(f"    エクイティ: start={eq[0]:.0f}  end={eq[-1]:.0f}  min={mn:.0f}  max={mx:.0f}")

    # Walk-forward
    if p["wf"]:
        print(f"\n  Walk-Forward:")
        for sym, w in p["wf"].items():
            ratio = w["avg_oos"] / w["avg_is"] if w["avg_is"] > 0 else 0
            judge = "★安定" if ratio >= 0.7 and w["avg_oos"] >= 1.0 else "△要注意" if ratio >= 0.5 else "×過学習"
            print(f"    {sym}: IS={w['avg_is']:.3f}  OOS={w['avg_oos']:.3f}  OOS/IS={ratio:.2f}  {judge}")
            print(f"         窓別OOS: {['%.3f'%p for p in w['oos_pfs']]}")


def _gen_mt4_ea(cfg, ea_name):
    """MT4 EA (MQL4) コードを生成"""
    sig = cfg["entry_signal"]
    rules = cfg["exit_rules"]
    filters = cfg.get("entry_filters", [])

    sig_type = sig["type"]
    tp_mult = rules.get("tp_atr_mult", 3.0)
    sl_mult = rules.get("sl_atr_mult", 1.0)
    atr_p = rules.get("atr_period", 14)
    use_be = rules.get("breakeven", False)
    be_pips = rules.get("be_trigger_pips", 0.03) * 100  # to pips
    use_trail = rules.get("trailing", False)
    trail_mult = rules.get("trail_atr_mult", 1.0)
    max_bars = rules.get("max_bars", 0)

    # セッションフィルタ
    sess = "all"
    for f in filters:
        if f.get("type") == "session_filter":
            sess = f.get("session", "all")

    # LowVol
    has_lv = any(f.get("type") == "atr_low_vola_filter" for f in filters)
    lv_lb = 60
    for f in filters:
        if f.get("type") == "atr_low_vola_filter":
            lv_lb = f.get("lookback", 60)

    # Signal-specific params
    if sig_type == "atr_break":
        period = sig.get("period", 14)
        multiplier = sig.get("multiplier", 1.5)
        signal_code = f"""
   double atr_val = iATR(NULL, 0, {period}, 1);
   double move = MathAbs(Close[1] - Close[2]);
   if(move > atr_val * {multiplier} && Close[1] > Close[2]) signal = 1;  // Buy
   if(move > atr_val * {multiplier} && Close[1] < Close[2]) signal = -1; // Sell"""
    elif sig_type == "hilo_break":
        lookback = sig.get("lookback", 15)
        confirm = sig.get("confirm_bars", 1)
        signal_code = f"""
   double highest = High[iHighest(NULL, 0, MODE_HIGH, {lookback}, 2)];
   double lowest  = Low[iLowest(NULL, 0, MODE_LOW, {lookback}, 2)];
   if(Close[1] > highest) signal = 1;   // Buy breakout
   if(Close[1] < lowest)  signal = -1;  // Sell breakout"""
    elif sig_type == "bb_bounce":
        bb_p = sig.get("period", 20)
        bb_std = sig.get("std_mult", 2.0)
        signal_code = f"""
   double bb_upper = iBands(NULL, 0, {bb_p}, {bb_std}, 0, PRICE_CLOSE, MODE_UPPER, 1);
   double bb_lower = iBands(NULL, 0, {bb_p}, {bb_std}, 0, PRICE_CLOSE, MODE_LOWER, 1);
   if(Close[1] <= bb_lower) signal = 1;   // Buy at lower band
   if(Close[1] >= bb_upper) signal = -1;  // Sell at upper band"""
    else:
        signal_code = "   // Unknown signal type"

    # Session filter
    if sess == "london":
        sess_code = "   if(Hour() < 7 || Hour() >= 16) return; // London only"
    elif sess == "newyork":
        sess_code = "   if(Hour() < 13 || Hour() >= 22) return; // NewYork only"
    else:
        sess_code = "   // No session filter"

    lv_code = ""
    if has_lv:
        lv_code = f"""
   // LowVol Filter: ATR must be below median of last {lv_lb} bars
   double atr_now = iATR(NULL, 0, {atr_p}, 0);
   double atr_arr[];
   ArrayResize(atr_arr, {lv_lb});
   for(int k=0; k<{lv_lb}; k++) atr_arr[k] = iATR(NULL, 0, {atr_p}, k);
   ArraySort(atr_arr);
   double atr_median = atr_arr[{lv_lb}//2];
   if(atr_now > atr_median) return; // Too volatile"""

    be_code = ""
    if use_be:
        be_code = f"""
   // Breakeven
   if(OrderType() == OP_BUY && Bid - OrderOpenPrice() >= {be_pips} * Point * 10)
      if(OrderStopLoss() < OrderOpenPrice())
         OrderModify(OrderTicket(), OrderOpenPrice(), OrderOpenPrice() + Point, OrderTakeProfit(), 0);
   if(OrderType() == OP_SELL && OrderOpenPrice() - Ask >= {be_pips} * Point * 10)
      if(OrderStopLoss() > OrderOpenPrice())
         OrderModify(OrderTicket(), OrderOpenPrice(), OrderOpenPrice() - Point, OrderTakeProfit(), 0);"""

    trail_code = ""
    if use_trail:
        trail_code = f"""
   // Trailing Stop (ATR-based)
   double trail_dist = iATR(NULL, 0, {atr_p}, 0) * {trail_mult};
   if(OrderType() == OP_BUY) {{
      double new_sl = Bid - trail_dist;
      if(new_sl > OrderStopLoss()) OrderModify(OrderTicket(), OrderOpenPrice(), new_sl, OrderTakeProfit(), 0);
   }}
   if(OrderType() == OP_SELL) {{
      double new_sl = Ask + trail_dist;
      if(new_sl < OrderStopLoss() || OrderStopLoss() == 0) OrderModify(OrderTicket(), OrderOpenPrice(), new_sl, OrderTakeProfit(), 0);
   }}"""

    maxbar_code = ""
    if max_bars > 0:
        maxbar_code = f"""
   // Max bars exit
   if(TimeCurrent() - OrderOpenTime() >= {max_bars} * 60) {{
      if(OrderType() == OP_BUY) OrderClose(OrderTicket(), OrderLots(), Bid, 3);
      if(OrderType() == OP_SELL) OrderClose(OrderTicket(), OrderLots(), Ask, 3);
   }}"""

    ea_code = f"""//+------------------------------------------------------------------+
//| {ea_name}.mq4
//| Auto-generated by FX Research Factory Phase 3
//| Strategy: {cfg['name']}
//+------------------------------------------------------------------+
#property copyright "FX Research Factory"
#property version   "1.00"
#property strict

input double LotSize = 0.1;
input int    MagicNumber = {hash(cfg['name']) % 100000};
input int    Slippage = 3;

int OnInit() {{ return(INIT_SUCCEEDED); }}
void OnDeinit(const int reason) {{}}

void OnTick()
{{
   // Skip if already in position
   for(int i=OrdersTotal()-1; i>=0; i--)
      if(OrderSelect(i, SELECT_BY_POS) && OrderMagicNumber() == MagicNumber)
      {{
         ManagePosition();
         return;
      }}

{sess_code}
{lv_code}

   int signal = 0;
{signal_code}

   if(signal == 0) return;

   double atr = iATR(NULL, 0, {atr_p}, 1);
   double tp_dist = atr * {tp_mult};
   double sl_dist = atr * {sl_mult};

   if(signal == 1) {{
      double price = Ask;
      double sl = price - sl_dist;
      double tp = price + tp_dist;
      OrderSend(NULL, OP_BUY, LotSize, price, Slippage, sl, tp, "{ea_name}", MagicNumber, 0, clrGreen);
   }}
   if(signal == -1) {{
      double price = Bid;
      double sl = price + sl_dist;
      double tp = price - tp_dist;
      OrderSend(NULL, OP_SELL, LotSize, price, Slippage, sl, tp, "{ea_name}", MagicNumber, 0, clrRed);
   }}
}}

void ManagePosition()
{{
   if(!OrderSelect(0, SELECT_BY_POS)) return;
{be_code}
{trail_code}
{maxbar_code}
}}
//+------------------------------------------------------------------+
"""
    return ea_code


def run_final_profile(settings):
    bal = settings.get("initial_balance", 100000)
    ecn = settings.get("ecn", {})
    sp = ecn.get("spread", ECN_SP); cm = ecn.get("commission", ECN_CM)
    dd = settings.get("data_dir", "data/raw"); rd = settings.get("results_dir", "results")
    isr = settings.get("research", {}).get("is_ratio", 0.7)

    alld = discover_data_files(dd)
    dfs = [d for d in alld if d["symbol"] in SYMS and d["timeframe"] == TF]

    print(f"\n{'#'*70}")
    print(f"  最終候補 詳細プロファイル + MT4 EA生成")
    print(f"{'#'*70}")
    print(f"  最終候補: {len(FINAL_CONFIGS)} 戦略")
    print(f"  ECN: spread={sp*100:.1f}pips + comm={cm*2*100:.1f}pips")

    ea_dir = os.path.join(rd, "ea_mt4")
    os.makedirs(ea_dir, exist_ok=True)

    for i, cfg in enumerate(FINAL_CONFIGS, 1):
        print(f"\n\n{'#'*70}")
        print(f"  候補 {i}/{len(FINAL_CONFIGS)}")
        print(f"{'#'*70}")

        # プロファイル
        profile = _profile_strategy(cfg, dfs, bal, sp, cm, isr)
        _print_profile(profile)

        # MT4 EA生成
        ea_name = f"FXFactory_{cfg['entry_signal']['type']}_{i:02d}"
        ea_code = _gen_mt4_ea(cfg, ea_name)
        ea_path = os.path.join(ea_dir, f"{ea_name}.mq4")
        with open(ea_path, "w", encoding="utf-8") as f:
            f.write(ea_code)
        print(f"\n  MT4 EA保存: {ea_path}")

    # 全候補の比較テーブル
    print(f"\n\n{'#'*70}")
    print(f"  最終候補 比較テーブル")
    print(f"{'#'*70}")
    print(f"\n  {'#':2s}  {'Label':40s}  {'GBPJPY':>8s}  {'EURJPY':>8s}  {'USDJPY':>8s}  {'WF安定':>6s}  {'sp0.5':>6s}")
    for i, cfg in enumerate(FINAL_CONFIGS, 1):
        p = _profile_strategy(cfg, dfs, bal, sp, cm, isr)
        pfs = {}
        for sym, d in p["currencies"].items():
            pfs[sym] = d["metrics"]["pf"]
        wf_ok = all(w["avg_oos"] >= 0.9 for w in p["wf"].values()) if p["wf"] else False
        print(f"  {i:2d}  {cfg.get('label','')[:40]:40s}  {pfs.get('GBPJPY',0):8.3f}  {pfs.get('EURJPY',0):8.3f}  {pfs.get('USDJPY',0):8.3f}  {'YES' if wf_ok else 'NO':>6s}")

    print(f"\n  EA保存先: {ea_dir}/")
    print(f"\n{'#'*70}")
    print(f"  Windows: cd fx_lab && python main.py --final")
    print(f"{'#'*70}")


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_dir)
    import yaml; os.makedirs("logs", exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.FileHandler("logs/final.log", encoding="utf-8"), logging.StreamHandler(sys.stdout)])
    with open(os.path.join("config", "settings.yaml"), "r", encoding="utf-8") as f:
        settings = yaml.safe_load(f)
    run_final_profile(settings)
