"""全シグナルタイプ総動員 M1スキャル探索

RSI単体はエッジ不足 (PF=0.75)。
エンジンが持つ全シグナルタイプを投入し、PF>=1.0を目指す。

シグナル:
  1. bb_bounce (BB反発)
  2. wick_reversal (ヒゲ反転)
  3. consecutive_reversal (連続足反転)
  4. rsi_reversal (RSI逆張り) ← 比較用
  5. momentum (モメンタム)
  6. donchian_break (ドンチャンブレイク)
  7. atr_break (ATR急増ブレイク)
  8. hilo_break (高値安値ブレイク)

ECN前提: spread=0.3pips, commission=0.5pips RT
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
ECN_COMMISSION_HALF = 0.0025
SPREAD_TEST_LEVELS = [0.002, 0.003, 0.005, 0.010]

TARGET_SYMBOLS = ["USDJPY", "EURJPY", "GBPJPY"]
TARGET_TIMEFRAME = "M1"

# ================================================================
# シグナルテンプレート (各タイプで複数バリエーション)
# ================================================================

SIGNAL_TEMPLATES = [
    # --- 平均回帰系 ---
    # BB反発 (RSIより構造的)
    {"type": "bb_bounce", "category": "mean_reversion", "period": 14, "std_mult": 2.0},
    {"type": "bb_bounce", "category": "mean_reversion", "period": 20, "std_mult": 2.0},
    {"type": "bb_bounce", "category": "mean_reversion", "period": 20, "std_mult": 1.5},
    {"type": "bb_bounce", "category": "mean_reversion", "period": 10, "std_mult": 2.0},
    {"type": "bb_bounce", "category": "mean_reversion", "period": 30, "std_mult": 2.5},

    # ヒゲ反転 (プライスアクション)
    {"type": "wick_reversal", "category": "mean_reversion", "wick_ratio": 1.5, "min_wick_atr": 0.3, "atr_period": 14},
    {"type": "wick_reversal", "category": "mean_reversion", "wick_ratio": 2.0, "min_wick_atr": 0.5, "atr_period": 14},
    {"type": "wick_reversal", "category": "mean_reversion", "wick_ratio": 1.5, "min_wick_atr": 0.5, "atr_period": 10},
    {"type": "wick_reversal", "category": "mean_reversion", "wick_ratio": 2.5, "min_wick_atr": 0.3, "atr_period": 14},
    {"type": "wick_reversal", "category": "mean_reversion", "wick_ratio": 1.0, "min_wick_atr": 0.8, "atr_period": 7},

    # 連続足反転
    {"type": "consecutive_reversal", "category": "mean_reversion", "consecutive_count": 3},
    {"type": "consecutive_reversal", "category": "mean_reversion", "consecutive_count": 4},
    {"type": "consecutive_reversal", "category": "mean_reversion", "consecutive_count": 5},

    # RSI逆張り (比較用)
    {"type": "rsi_reversal", "category": "mean_reversion", "period": 7, "oversold": 35, "overbought": 65},
    {"type": "rsi_reversal", "category": "mean_reversion", "period": 5, "oversold": 30, "overbought": 70},

    # --- ブレイクアウト系 ---
    # ドンチャンブレイク
    {"type": "donchian_break", "category": "breakout", "period": 10},
    {"type": "donchian_break", "category": "breakout", "period": 15},
    {"type": "donchian_break", "category": "breakout", "period": 20},
    {"type": "donchian_break", "category": "breakout", "period": 30},

    # ATRブレイク
    {"type": "atr_break", "category": "breakout", "period": 10, "multiplier": 1.5},
    {"type": "atr_break", "category": "breakout", "period": 14, "multiplier": 2.0},
    {"type": "atr_break", "category": "breakout", "period": 7, "multiplier": 1.0},

    # 高値安値ブレイク
    {"type": "hilo_break", "category": "breakout", "lookback": 10, "confirm_bars": 1},
    {"type": "hilo_break", "category": "breakout", "lookback": 20, "confirm_bars": 1},
    {"type": "hilo_break", "category": "breakout", "lookback": 15, "confirm_bars": 2},

    # --- トレンドフォロー系 ---
    # モメンタム
    {"type": "momentum", "category": "trend_follow", "period": 5},
    {"type": "momentum", "category": "trend_follow", "period": 10},
    {"type": "momentum", "category": "trend_follow", "period": 15},
]

# TP/SL: 非対称を含む (大TP小SLでトレンド系、小TP大SLで逆張り系)
TP_SL_CONFIGS = [
    # 対称
    {"tp_type": "fixed", "tp_pips": 0.05, "sl_type": "fixed", "sl_pips": 0.05},
    {"tp_type": "fixed", "tp_pips": 0.07, "sl_type": "fixed", "sl_pips": 0.07},
    {"tp_type": "fixed", "tp_pips": 0.10, "sl_type": "fixed", "sl_pips": 0.10},
    {"tp_type": "fixed", "tp_pips": 0.15, "sl_type": "fixed", "sl_pips": 0.15},
    # 大TP (トレンド・ブレイク向き: 損小利大)
    {"tp_type": "fixed", "tp_pips": 0.15, "sl_type": "fixed", "sl_pips": 0.05},
    {"tp_type": "fixed", "tp_pips": 0.20, "sl_type": "fixed", "sl_pips": 0.07},
    {"tp_type": "fixed", "tp_pips": 0.15, "sl_type": "fixed", "sl_pips": 0.07},
    # 大SL (逆張り向き: 損大利小だが高勝率)
    {"tp_type": "fixed", "tp_pips": 0.05, "sl_type": "fixed", "sl_pips": 0.10},
    {"tp_type": "fixed", "tp_pips": 0.05, "sl_type": "fixed", "sl_pips": 0.15},
    {"tp_type": "fixed", "tp_pips": 0.07, "sl_type": "fixed", "sl_pips": 0.15},
    # ATRベース (ボラ適応)
    {"tp_type": "atr_mult", "tp_atr_mult": 1.5, "sl_type": "atr_mult", "sl_atr_mult": 1.0},
    {"tp_type": "atr_mult", "tp_atr_mult": 2.0, "sl_type": "atr_mult", "sl_atr_mult": 1.0},
    {"tp_type": "atr_mult", "tp_atr_mult": 2.0, "sl_type": "atr_mult", "sl_atr_mult": 1.5},
    {"tp_type": "atr_mult", "tp_atr_mult": 3.0, "sl_type": "atr_mult", "sl_atr_mult": 1.5},
]

SESSION_FILTERS = [
    [{"type": "session_filter", "session": "london"}],
    [{"type": "session_filter", "session": "newyork"}],
]

FILTER_OPTIONS = [
    [],
    [{"type": "atr_low_vola_filter", "lookback": 60}],
    [{"type": "atr_low_vola_filter", "lookback": 120}],
]

MAX_BARS_OPTIONS = [{}, {"max_bars": 15}, {"max_bars": 30}, {"max_bars": 60}]
BE_OPTIONS = [{}, {"breakeven": True, "be_trigger_pips": 0.03}]
TRAIL_OPTIONS = [
    {},
    {"trailing": True, "trail_type": "fixed", "trail_distance": 0.03},
    {"trailing": True, "trail_type": "atr_mult", "trail_atr_mult": 1.0},
]
ATR_PERIODS = [7, 10, 14]


def _gen_configs(target: int = 250) -> list[dict]:
    random.seed(9999)
    configs = []
    seen = set()
    attempts = 0

    while len(configs) < target and attempts < target * 30:
        attempts += 1
        sig = random.choice(SIGNAL_TEMPLATES)
        tpsl = random.choice(TP_SL_CONFIGS)
        sess = random.choice(SESSION_FILTERS)
        filt = random.choice(FILTER_OPTIONS)
        mb = random.choice(MAX_BARS_OPTIONS)
        be = random.choice(BE_OPTIONS)
        trail = random.choice(TRAIL_OPTIONS)
        atr_p = random.choice(ATR_PERIODS)

        exit_rules = {**tpsl, "atr_period": atr_p, **mb, **be, **trail}
        config = {
            "entry_signal": dict(sig),
            "entry_filters": sess + filt,
            "exit_rules": exit_rules,
        }
        config["name"] = _make_name(config)
        h = hashlib.md5(json.dumps(config, sort_keys=True, default=str).encode()).hexdigest()
        if h not in seen:
            seen.add(h)
            configs.append(config)
    return configs


def _info(cfg):
    sig = cfg["entry_signal"]
    rules = cfg["exit_rules"]
    filters = cfg.get("entry_filters", [])
    tp_d = f"{rules.get('tp_pips',0)*100:.0f}p" if rules.get("tp_type") == "fixed" else f"ATR×{rules.get('tp_atr_mult',0)}"
    sl_d = f"{rules.get('sl_pips',0)*100:.0f}p" if rules.get("sl_type") == "fixed" else f"ATR×{rules.get('sl_atr_mult',0)}"
    sess = "all"
    has_lv = False
    for f in filters:
        if f.get("type") == "session_filter": sess = f.get("session", "all")
        if f.get("type") == "atr_low_vola_filter": has_lv = True
    return {
        "sig_type": sig["type"], "category": sig.get("category", "?"),
        "tp_display": tp_d, "sl_display": sl_d,
        "session": sess, "has_lowvol": has_lv,
        "has_breakeven": bool(rules.get("breakeven")),
        "has_trailing": bool(rules.get("trailing")),
        "max_bars": rules.get("max_bars", 0),
    }


def _run_oos(configs, data_files, balance, spread, commission, is_ratio=0.7):
    results = []
    total = len(configs) * len(data_files)
    with tqdm(total=total, desc="  全シグナルOOSテスト") as pbar:
        for di in data_files:
            sym, tf = di["symbol"], di["timeframe"]
            try:
                df = load_ohlc(di["filepath"])
                _, oos = split_is_oos(df, is_ratio=is_ratio)
            except Exception as e:
                pbar.update(len(configs)); continue
            for cfg in configs:
                try:
                    strat = ConfigurableStrategy(config=cfg, spread=spread, commission=commission)
                    trades = strat.backtest(oos, initial_balance=balance)
                    r = evaluate_strategy(trades, balance)
                    r["strategy_name"] = cfg["name"]
                    r["symbol"] = sym; r["timeframe"] = tf
                    r.update(_info(cfg))
                    r["avg_hold_min"] = round(r["avg_holding_seconds"] / 60, 1)
                    if trades:
                        sp_ = {"tokyo": 0.0, "london": 0.0, "newyork": 0.0}
                        sc_ = {"tokyo": 0, "london": 0, "newyork": 0}
                        for t in trades:
                            s = _classify_session(t.entry_time.hour)
                            sp_[s] += t.pnl; sc_[s] += 1
                        for k in sp_: r[f"pnl_{k}"] = round(sp_[k], 2); r[f"trades_{k}"] = sc_[k]
                    else:
                        for k in ["tokyo","london","newyork"]: r[f"pnl_{k}"] = 0.0; r[f"trades_{k}"] = 0
                    results.append(r)
                except Exception as e:
                    logger.error(f"失敗 ({cfg['name']}): {e}")
                finally:
                    pbar.update(1)
    return results


def _run_spread_sens(configs, data_files, balance, is_ratio=0.7):
    rows = []
    total = len(configs) * len(data_files) * len(SPREAD_TEST_LEVELS)
    with tqdm(total=total, desc="  Spread感応度") as pbar:
        for di in data_files:
            sym, tf = di["symbol"], di["timeframe"]
            try:
                df = load_ohlc(di["filepath"])
                _, oos = split_is_oos(df, is_ratio=is_ratio)
            except Exception:
                pbar.update(len(configs) * len(SPREAD_TEST_LEVELS)); continue
            for cfg in configs:
                for sp in SPREAD_TEST_LEVELS:
                    try:
                        strat = ConfigurableStrategy(config=cfg, spread=sp, commission=ECN_COMMISSION_HALF)
                        trades = strat.backtest(oos, initial_balance=balance)
                        r = evaluate_strategy(trades, balance)
                        rows.append({
                            "strategy_name": cfg["name"], "symbol": sym,
                            "spread_pips": sp * 100, "pf": r["pf"],
                            "trade_count": r["trade_count"],
                            "sig_type": cfg["entry_signal"]["type"],
                        })
                    except Exception: pass
                    finally: pbar.update(1)
    return rows


def _cap(v, c=10.0):
    if v == float("inf") or v != v: return c
    return min(v, c)


def run_all_signals(settings: dict) -> None:
    balance = settings.get("initial_balance", 100000)
    ecn = settings.get("ecn", {})
    spread = ecn.get("spread", ECN_SPREAD)
    commission = ecn.get("commission", ECN_COMMISSION_HALF)
    data_dir = settings.get("data_dir", "data/raw")
    results_dir = settings.get("results_dir", "results")
    is_ratio = settings.get("research", {}).get("is_ratio", 0.7)
    ranked_dir = os.path.join(results_dir, "ranked")
    os.makedirs(ranked_dir, exist_ok=True)

    cost = (spread + commission * 2) * 100
    print(f"\n{'='*70}")
    print(f"  全シグナルタイプ総動員 M1スキャル探索")
    print(f"{'='*70}")
    print(f"  ECN: spread={spread*100:.1f}pips + comm={commission*2*100:.1f}pips = {cost:.1f}pips/trade")

    all_data = discover_data_files(data_dir)
    data_files = [d for d in all_data if d["symbol"] in TARGET_SYMBOLS and d["timeframe"] == TARGET_TIMEFRAME]
    if not data_files: print("  データなし"); return

    # Phase 1
    print(f"\n  Phase 1: 戦略生成")
    configs = _gen_configs(target=250)
    print(f"  生成: {len(configs)} 個")
    sig_dist = Counter(c["entry_signal"]["type"] for c in configs)
    cat_dist = Counter(c["entry_signal"].get("category","?") for c in configs)
    print(f"  シグナル分布: {dict(sig_dist)}")
    print(f"  カテゴリ分布: {dict(cat_dist)}")

    # Phase 2
    total = len(configs) * len(data_files)
    print(f"\n  Phase 2: OOSバックテスト ({len(configs)} × {len(data_files)} = {total})")
    all_results = _run_oos(configs, data_files, balance, spread, commission, is_ratio)
    print(f"  結果: {len(all_results)}")
    if not all_results: return

    df = pd.DataFrame(all_results)
    df.to_csv(os.path.join(results_dir, "all_signals_ecn.csv"), index=False, encoding="utf-8-sig")

    # Phase 3: 候補
    print(f"\n  Phase 3: 候補抽出")
    fin = np.isfinite(df["pf"])
    expl = df[fin & (df["pf"] >= 1.00) & (df["max_dd_pct"] <= 20) & (df["trade_count"] >= 500)].copy()
    expl = expl.sort_values("pf", ascending=False).reset_index(drop=True)
    strong = df[fin & (df["pf"] >= 1.10) & (df["max_dd_pct"] <= 15) & (df["trade_count"] >= 1000)].copy()
    strong = strong.sort_values("pf", ascending=False).reset_index(drop=True)

    print(f"  exploration (PF≥1.00, DD≤20%, trades≥500): {len(expl)}")
    print(f"  strong      (PF≥1.10, DD≤15%, trades≥1000): {len(strong)}")

    ecn_csv = os.path.join(ranked_dir, "all_signals_ecn.csv")
    expl.to_csv(ecn_csv, index=False, encoding="utf-8-sig")

    if not expl.empty:
        print(f"\n  --- PF≥1.0 候補 TOP30 ---")
        for i, (_, r) in enumerate(expl.head(30).iterrows(), 1):
            lv = "LV" if r.get("has_lowvol") else "--"
            tr = "TR" if r.get("has_trailing") else "--"
            be = "BE" if r.get("has_breakeven") else "--"
            mb = f"{r['max_bars']}m" if r.get("max_bars", 0) > 0 else "--"
            print(f"    {i:2d}. {r['symbol']}_M1 [{r['session']:8s}]  PF={r['pf']:.3f}  WR={r['winrate']:.1f}%  DD={r['max_dd_pct']:.1f}%  trades={r['trade_count']:.0f}  hold={r['avg_hold_min']:.0f}m  {r['sig_type']:20s}  TP={r['tp_display']:8s} SL={r['sl_display']:8s}  [{lv} {be} {tr} {mb}]")

    if not strong.empty:
        print(f"\n  --- Strong候補 (PF≥1.10) TOP10 ---")
        for i, (_, r) in enumerate(strong.head(10).iterrows(), 1):
            print(f"    {i:2d}. {r['symbol']}_M1 [{r['session']:8s}]  PF={r['pf']:.3f}  WR={r['winrate']:.1f}%  trades={r['trade_count']:.0f}  {r['sig_type']:20s}  TP={r['tp_display']} SL={r['sl_display']}")

    # Phase 4: Spread sensitivity (上位戦略のみ)
    print(f"\n  Phase 4: Spread感応度テスト")
    if not expl.empty:
        top_names = set(expl["strategy_name"].unique())
    else:
        top_names = set(df.nlargest(40, "pf")["strategy_name"].unique())
    sens_cfgs = [c for c in configs if c["name"] in top_names]
    print(f"  対象: {len(sens_cfgs)} 戦略")

    sens_rows = _run_spread_sens(sens_cfgs, data_files, balance, is_ratio)
    if sens_rows:
        sdf = pd.DataFrame(sens_rows)
        sdf["pf_cap"] = sdf["pf"].apply(_cap)
        pivot = sdf.groupby(["strategy_name", "spread_pips"]).agg(
            avg_pf=("pf_cap", "mean"), avg_trades=("trade_count", "mean"),
        ).reset_index()
        pw = pivot.pivot(index="strategy_name", columns="spread_pips", values="avg_pf")
        pw.columns = [f"pf_sp{c:.1f}" for c in pw.columns]
        pw = pw.reset_index()
        sp05 = "pf_sp0.5"
        if sp05 in pw.columns:
            pw["robust"] = pw[sp05] >= 1.00
            robust = pw[pw["robust"]]
            print(f"  robust (spread=0.5でPF≥1.0): {len(robust)}")
        else:
            robust = pd.DataFrame()
        rob_csv = os.path.join(ranked_dir, "all_signals_spread_robust.csv")
        pw.sort_values(sp05 if sp05 in pw.columns else pw.columns[1], ascending=False).to_csv(
            rob_csv, index=False, encoding="utf-8-sig")
        print(f"  保存: {rob_csv}")

        print(f"\n  --- Spread耐性TOP15 ---")
        show = pw.sort_values(sp05 if sp05 in pw.columns else pw.columns[1], ascending=False).head(15)
        for _, r in show.iterrows():
            cols = [c for c in pw.columns if c.startswith("pf_sp")]
            vals = "  ".join(f"{c}={r[c]:.3f}" for c in cols)
            rob = "ROBUST" if r.get("robust", False) else ""
            # find sig type
            nm = r["strategy_name"]
            st_match = sdf[sdf["strategy_name"] == nm]
            st_type = st_match["sig_type"].iloc[0] if not st_match.empty else "?"
            print(f"    {nm[:30]:30s}  {st_type:20s}  {vals}  {rob}")

    # Phase 5: 分析
    print(f"\n{'='*70}")
    print(f"  シグナルタイプ別分析")
    print(f"{'='*70}")

    st = df[df["trade_count"] >= 50].copy()
    st["pf"] = st["pf"].apply(_cap)

    if not st.empty:
        # シグナルタイプ別
        print(f"\n  --- シグナルタイプ別 (trades≥50) ---")
        sg = st.groupby("sig_type").agg(
            avg_pf=("pf", "mean"), med_pf=("pf", "median"), max_pf=("pf", "max"),
            avg_wr=("winrate", "mean"), avg_trades=("trade_count", "mean"),
            avg_hold=("avg_hold_min", "mean"),
            count=("pf", "count"),
            pf_ge1=("pf", lambda x: (x >= 1.0).sum()),
        ).sort_values("avg_pf", ascending=False)
        for idx, r in sg.iterrows():
            print(f"    {idx:25s}  avgPF={r['avg_pf']:.3f}  medPF={r['med_pf']:.3f}  maxPF={r['max_pf']:.3f}  WR={r['avg_wr']:.1f}%  trades={r['avg_trades']:.0f}  hold={r['avg_hold']:.0f}m  PF≥1.0={r['pf_ge1']:.0f}/{r['count']:.0f}")

        # カテゴリ別
        print(f"\n  --- カテゴリ別 ---")
        cg = st.groupby("category").agg(
            avg_pf=("pf", "mean"), med_pf=("pf", "median"), max_pf=("pf", "max"),
            pf_ge1=("pf", lambda x: (x >= 1.0).sum()), count=("pf", "count"),
        ).sort_values("avg_pf", ascending=False)
        for idx, r in cg.iterrows():
            print(f"    {idx:20s}  avgPF={r['avg_pf']:.3f}  medPF={r['med_pf']:.3f}  maxPF={r['max_pf']:.3f}  PF≥1.0={r['pf_ge1']:.0f}/{r['count']:.0f}")

        # 通貨別
        print(f"\n  --- 通貨別 ---")
        symg = st.groupby("symbol").agg(
            avg_pf=("pf", "mean"), max_pf=("pf", "max"),
            pf_ge1=("pf", lambda x: (x >= 1.0).sum()),
        ).sort_values("avg_pf", ascending=False)
        for idx, r in symg.iterrows():
            print(f"    {idx:10s}  avgPF={r['avg_pf']:.3f}  maxPF={r['max_pf']:.3f}  PF≥1.0={r['pf_ge1']:.0f}")

        # セッション別
        print(f"\n  --- セッション別 ---")
        sessg = st.groupby("session").agg(
            avg_pf=("pf", "mean"), pf_ge1=("pf", lambda x: (x >= 1.0).sum()),
        ).sort_values("avg_pf", ascending=False)
        for idx, r in sessg.iterrows():
            print(f"    {idx:10s}  avgPF={r['avg_pf']:.3f}  PF≥1.0={r['pf_ge1']:.0f}")

        # TP/SL別 (タイプ×非対称性)
        print(f"\n  --- TP/SL別 ---")
        st["tpsl"] = st["tp_display"] + "/" + st["sl_display"]
        tpg = st.groupby("tpsl").agg(
            avg_pf=("pf", "mean"), max_pf=("pf", "max"), avg_wr=("winrate", "mean"),
            count=("pf", "count"), pf_ge1=("pf", lambda x: (x >= 1.0).sum()),
        ).sort_values("avg_pf", ascending=False)
        for idx, r in tpg.iterrows():
            print(f"    {idx:20s}  avgPF={r['avg_pf']:.3f}  maxPF={r['max_pf']:.3f}  WR={r['avg_wr']:.1f}%  PF≥1.0={r['pf_ge1']:.0f}/{r['count']:.0f}")

    # === 結論 ===
    print(f"\n{'='*70}")
    print(f"  結論")
    print(f"{'='*70}")
    n_expl = len(expl)
    n_strong = len(strong)
    n_robust = len(robust) if not robust.empty else 0
    print(f"  exploration候補: {n_expl}")
    print(f"  strong候補:      {n_strong}")
    print(f"  robust候補:      {n_robust}")

    if not sg.empty:
        best_sig = sg.index[0]
        print(f"  最良シグナル: {best_sig}")
    if not cg.empty:
        best_cat = cg.index[0]
        print(f"  最良カテゴリ: {best_cat}")

    if n_strong > 0:
        print(f"\n  PF≥1.1の戦略が見つかった！ 次は walk-forward とパラメータ最適化。")
    elif n_expl > 0:
        print(f"\n  PF≥1.0の候補あり。微調整で改善の可能性。")
    else:
        print(f"\n  全シグナルタイプでPF<1.0。M1×ECNでのエッジ獲得は極めて困難。")

    print(f"\n{'='*70}")
    print(f"  Windows実行コマンド")
    print(f"{'='*70}")
    print(f"  cd fx_lab")
    print(f"  python main.py --all-signals")
    print(f"{'='*70}")


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_dir)
    import yaml
    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.FileHandler("logs/all_signals.log", encoding="utf-8"), logging.StreamHandler(sys.stdout)])
    with open(os.path.join("config", "settings.yaml"), "r", encoding="utf-8") as f:
        settings = yaml.safe_load(f)
    run_all_signals(settings)
