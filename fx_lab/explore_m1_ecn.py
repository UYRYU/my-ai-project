"""ECN口座前提 M1スキャルピング探索

コスト前提:
  spread: 0.3pips (0.003円)
  commission round-turn: 0.5pips (0.005円)
  合計: 0.8pips/trade

対象: USDJPY/EURJPY/GBPJPY × M1
RSI: 5,6,7 / 閾値 30/70, 35/65, 40/60
TP/SL: 固定 5,7,10 pips
フィルタ: LowVolのみ or なし

評価:
  exploration: OOS PF>=1.00, DD<=20%, trades>=1000
  strong:      OOS PF>=1.10, DD<=15%, trades>=1500
  robust:      spread=0.5でPF>=1.00維持

spread sensitivity test: 0.2, 0.3, 0.5, 1.0 pips (commission固定0.5pips)
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

# ================================================================
# ECNコスト定数
# ================================================================
ECN_SPREAD = 0.003          # 0.3pips
ECN_COMMISSION_HALF = 0.0025  # 片道0.25pips (往復0.5pips)

# spread sensitivity テスト用
SPREAD_TEST_LEVELS = [0.002, 0.003, 0.005, 0.010]  # 0.2, 0.3, 0.5, 1.0 pips
COMMISSION_FIXED_HALF = 0.0025  # 片道0.25pips固定

# ================================================================
# 戦略パラメータ
# ================================================================
TARGET_SYMBOLS = ["USDJPY", "EURJPY", "GBPJPY"]
TARGET_TIMEFRAME = "M1"

RSI_PERIODS = [5, 6, 7]
ENTRY_THRESHOLDS = [
    (30, 70),
    (35, 65),
    (40, 60),
]

# TP/SL: 固定pips (JPYペア: 0.01 = 1pip)
TP_SL_PIPS = [
    (0.05, 0.05),   # TP5/SL5
    (0.05, 0.07),   # TP5/SL7
    (0.05, 0.10),   # TP5/SL10
    (0.07, 0.05),   # TP7/SL5
    (0.07, 0.07),   # TP7/SL7
    (0.07, 0.10),   # TP7/SL10
    (0.10, 0.05),   # TP10/SL5
    (0.10, 0.07),   # TP10/SL7
    (0.10, 0.10),   # TP10/SL10
]

MAX_BARS_OPTIONS = [
    {},
    {"max_bars": 15},
    {"max_bars": 30},
]

BREAKEVEN_OPTIONS = [
    {},
    {"breakeven": True, "be_trigger_pips": 0.03},
]

# LowVolフィルタのみ
FILTER_OPTIONS = [
    [],  # なし
    [{"type": "atr_low_vola_filter", "lookback": 60}],
    [{"type": "atr_low_vola_filter", "lookback": 120}],
]

SESSION_FILTERS = [
    [{"type": "session_filter", "session": "london"}],
    [{"type": "session_filter", "session": "newyork"}],
]

ATR_PERIODS = [7, 10, 14]


def _generate_ecn_scalp_configs(target_count: int = 150) -> list[dict]:
    """ECN M1スキャル戦略を体系生成"""
    random.seed(2024)
    configs = []
    seen = set()

    # 全コア
    core = list(itertools.product(
        RSI_PERIODS, ENTRY_THRESHOLDS, TP_SL_PIPS, ATR_PERIODS,
    ))
    random.shuffle(core)

    attempts = 0
    ci = 0
    while len(configs) < target_count and attempts < target_count * 30:
        attempts += 1
        if ci >= len(core):
            ci = 0
            random.shuffle(core)

        rsi_p, (os_, ob), (tp, sl), atr_p = core[ci]
        ci += 1

        sess = random.choice(SESSION_FILTERS)
        filt = random.choice(FILTER_OPTIONS)
        be = random.choice(BREAKEVEN_OPTIONS)
        mb = random.choice(MAX_BARS_OPTIONS)

        config = {
            "entry_signal": {
                "type": "rsi_reversal",
                "category": "mean_reversion",
                "period": rsi_p,
                "oversold": os_,
                "overbought": ob,
            },
            "entry_filters": sess + filt,
            "exit_rules": {
                "tp_type": "fixed", "tp_pips": tp,
                "sl_type": "fixed", "sl_pips": sl,
                "atr_period": atr_p,
                **be, **mb,
            },
        }
        config["name"] = _make_name(config)
        h = hashlib.md5(json.dumps(config, sort_keys=True, default=str).encode()).hexdigest()
        if h not in seen:
            seen.add(h)
            configs.append(config)

    logger.info(f"ECN M1スキャル戦略 {len(configs)} 個生成")
    return configs


def _extract_info(cfg: dict) -> dict:
    sig = cfg["entry_signal"]
    rules = cfg["exit_rules"]
    filters = cfg.get("entry_filters", [])
    info = {
        "rsi_period": sig["period"],
        "oversold": sig["oversold"],
        "overbought": sig["overbought"],
        "tp_pips": rules.get("tp_pips", 0),
        "sl_pips": rules.get("sl_pips", 0),
        "has_breakeven": bool(rules.get("breakeven")),
        "max_bars": rules.get("max_bars", 0),
        "has_lowvol": False,
        "session": "all",
    }
    for f in filters:
        if f.get("type") == "session_filter":
            info["session"] = f.get("session", "all")
        elif f.get("type") == "atr_low_vola_filter":
            info["has_lowvol"] = True
    info["tp_display"] = f"{info['tp_pips']*100:.0f}p"
    info["sl_display"] = f"{info['sl_pips']*100:.0f}p"
    info["threshold"] = f"{info['oversold']}/{info['overbought']}"
    return info


def _run_oos(configs, data_files, balance, spread, commission, is_ratio=0.7):
    results = []
    total = len(configs) * len(data_files)
    with tqdm(total=total, desc="  ECN OOSテスト") as pbar:
        for di in data_files:
            sym, tf = di["symbol"], di["timeframe"]
            try:
                df = load_ohlc(di["filepath"])
                _, oos = split_is_oos(df, is_ratio=is_ratio)
            except Exception as e:
                logger.error(f"データ読み込み失敗: {sym}_{tf}: {e}")
                pbar.update(len(configs))
                continue

            for cfg in configs:
                try:
                    strat = ConfigurableStrategy(config=cfg, spread=spread, commission=commission)
                    trades = strat.backtest(oos, initial_balance=balance)
                    r = evaluate_strategy(trades, balance)
                    r["strategy_name"] = cfg["name"]
                    r["symbol"] = sym
                    r["timeframe"] = tf
                    r.update(_extract_info(cfg))
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
                    logger.error(f"失敗 ({cfg['name']}, {sym}_{tf}): {e}")
                finally:
                    pbar.update(1)
    return results


def _run_spread_sensitivity(configs, data_files, balance, is_ratio=0.7):
    """各戦略×各spread水準でPFを計測"""
    rows = []
    # 候補のconfigだけに絞って実施
    total = len(configs) * len(data_files) * len(SPREAD_TEST_LEVELS)
    with tqdm(total=total, desc="  Spread感応度テスト") as pbar:
        for di in data_files:
            sym, tf = di["symbol"], di["timeframe"]
            try:
                df = load_ohlc(di["filepath"])
                _, oos = split_is_oos(df, is_ratio=is_ratio)
            except Exception:
                pbar.update(len(configs) * len(SPREAD_TEST_LEVELS))
                continue

            for cfg in configs:
                name = cfg["name"]
                for sp_level in SPREAD_TEST_LEVELS:
                    try:
                        strat = ConfigurableStrategy(
                            config=cfg, spread=sp_level, commission=COMMISSION_FIXED_HALF
                        )
                        trades = strat.backtest(oos, initial_balance=balance)
                        r = evaluate_strategy(trades, balance)
                        rows.append({
                            "strategy_name": name,
                            "symbol": sym,
                            "timeframe": tf,
                            "spread_pips": sp_level * 100,
                            "pf": r["pf"],
                            "winrate": r["winrate"],
                            "total_pnl": r["total_pnl"],
                            "trade_count": r["trade_count"],
                            "max_dd_pct": r["max_dd_pct"],
                        })
                    except Exception:
                        pass
                    finally:
                        pbar.update(1)
    return rows


def _cap(v, c=10.0):
    if v == float("inf") or v != v: return c
    return min(v, c)


def run_ecn_scalp(settings: dict) -> None:
    balance = settings.get("initial_balance", 100000)
    ecn = settings.get("ecn", {})
    spread = ecn.get("spread", ECN_SPREAD)
    commission = ecn.get("commission", ECN_COMMISSION_HALF)
    data_dir = settings.get("data_dir", "data/raw")
    results_dir = settings.get("results_dir", "results")
    is_ratio = settings.get("research", {}).get("is_ratio", 0.7)
    ranked_dir = os.path.join(results_dir, "ranked")
    os.makedirs(ranked_dir, exist_ok=True)

    cost_total = (spread + commission * 2) * 100  # pips
    print(f"\n{'='*70}")
    print(f"  ECN口座前提 M1スキャルピング探索")
    print(f"{'='*70}")
    print(f"  spread: {spread*100:.1f}pips  commission RT: {commission*2*100:.1f}pips  合計: {cost_total:.1f}pips/trade")
    print(f"  対象: {', '.join(TARGET_SYMBOLS)} × M1")
    print(f"  RSI: {RSI_PERIODS} / 閾値: {[f'{o}/{b}' for o,b in ENTRY_THRESHOLDS]}")
    print(f"  TP/SL: 5/7/10 pips 固定組み合わせ")
    print(f"  フィルタ: LowVol or なし")

    all_data = discover_data_files(data_dir)
    data_files = [d for d in all_data if d["symbol"] in TARGET_SYMBOLS and d["timeframe"] == TARGET_TIMEFRAME]
    if not data_files:
        print("  対象データなし"); return
    for d in data_files:
        print(f"    - {d['symbol']}_{d['timeframe']}")

    # === Phase 1: 生成 ===
    print(f"\n  Phase 1: 戦略生成...")
    configs = _generate_ecn_scalp_configs(target_count=150)
    print(f"  生成: {len(configs)} 個")
    rsi_d = Counter(c["entry_signal"]["period"] for c in configs)
    th_d = Counter(f"{c['entry_signal']['oversold']}/{c['entry_signal']['overbought']}" for c in configs)
    sess_d = Counter()
    for c in configs:
        for f in c.get("entry_filters", []):
            if f.get("type") == "session_filter": sess_d[f["session"]] += 1
    print(f"  RSI期間: {dict(rsi_d)}")
    print(f"  閾値: {dict(th_d)}")
    print(f"  セッション: {dict(sess_d)}")

    # === Phase 2: OOSバックテスト ===
    total = len(configs) * len(data_files)
    print(f"\n  Phase 2: OOSバックテスト ({len(configs)} × {len(data_files)} = {total})")
    all_results = _run_oos(configs, data_files, balance, spread, commission, is_ratio)
    print(f"  結果: {len(all_results)}")
    if not all_results:
        print("  結果なし"); return

    df = pd.DataFrame(all_results)
    df.to_csv(os.path.join(results_dir, "m1_ecn_all.csv"), index=False, encoding="utf-8-sig")

    # === Phase 3: 候補抽出 ===
    print(f"\n  Phase 3: 候補抽出")
    fin = np.isfinite(df["pf"])

    # exploration候補
    expl = df[fin & (df["pf"] >= 1.00) & (df["max_dd_pct"] <= 20) & (df["trade_count"] >= 1000)].copy()
    expl = expl.sort_values("pf", ascending=False).reset_index(drop=True)
    print(f"  exploration (PF≥1.00, DD≤20%, trades≥1000): {len(expl)}")

    # strong候補
    strong = df[fin & (df["pf"] >= 1.10) & (df["max_dd_pct"] <= 15) & (df["trade_count"] >= 1500)].copy()
    strong = strong.sort_values("pf", ascending=False).reset_index(drop=True)
    print(f"  strong      (PF≥1.10, DD≤15%, trades≥1500): {len(strong)}")

    # 保存
    ecn_csv = os.path.join(ranked_dir, "m1_scalp_ecn.csv")
    expl.to_csv(ecn_csv, index=False, encoding="utf-8-sig")
    print(f"  保存: {ecn_csv}")

    if not expl.empty:
        print(f"\n  --- Exploration候補 TOP20 ---")
        for i, (_, r) in enumerate(expl.head(20).iterrows(), 1):
            lv = "LV" if r.get("has_lowvol") else "--"
            be = "BE" if r.get("has_breakeven") else "--"
            print(f"    {i:2d}. {r['symbol']}_M1 [{r['session']:8s}]  PF={r['pf']:.3f}  WR={r['winrate']:.1f}%  DD={r['max_dd_pct']:.1f}%  trades={r['trade_count']:.0f}  hold={r['avg_hold_min']:.0f}m  TP={r['tp_display']} SL={r['sl_display']}  RSI({r['rsi_period']}) {r['threshold']}  [{lv} {be}]")

    if not strong.empty:
        print(f"\n  --- Strong候補 TOP10 ---")
        for i, (_, r) in enumerate(strong.head(10).iterrows(), 1):
            print(f"    {i:2d}. {r['symbol']}_M1 [{r['session']:8s}]  PF={r['pf']:.3f}  WR={r['winrate']:.1f}%  DD={r['max_dd_pct']:.1f}%  trades={r['trade_count']:.0f}  RSI({r['rsi_period']}) {r['threshold']}  TP={r['tp_display']} SL={r['sl_display']}")

    # === Phase 4: Spread Sensitivity ===
    print(f"\n  Phase 4: Spread感応度テスト")
    print(f"  テスト水準: {[f'{s*100:.1f}pips' for s in SPREAD_TEST_LEVELS]} (commission固定0.5pips RT)")

    # exploration候補のconfigだけでテスト
    if expl.empty:
        # 候補なければ上位30戦略でテスト
        top_names = set(df.nlargest(30, "pf")["strategy_name"].unique())
    else:
        top_names = set(expl["strategy_name"].unique())
    sens_configs = [c for c in configs if c["name"] in top_names]
    print(f"  対象戦略: {len(sens_configs)}")

    sens_rows = _run_spread_sensitivity(sens_configs, data_files, balance, is_ratio)
    if sens_rows:
        sens_df = pd.DataFrame(sens_rows)
        sens_df["pf_capped"] = sens_df["pf"].apply(_cap)

        # 戦略×spread水準でピボット (全通貨平均)
        pivot = sens_df.groupby(["strategy_name", "spread_pips"]).agg(
            avg_pf=("pf_capped", "mean"),
            avg_trades=("trade_count", "mean"),
        ).reset_index()
        pivot_wide = pivot.pivot(index="strategy_name", columns="spread_pips", values="avg_pf")
        pivot_wide.columns = [f"pf_sp{c:.1f}" for c in pivot_wide.columns]
        pivot_wide = pivot_wide.reset_index()

        # robust判定: spread=0.5pips列のPF >= 1.00
        sp05_col = "pf_sp0.5"
        if sp05_col in pivot_wide.columns:
            pivot_wide["robust"] = pivot_wide[sp05_col] >= 1.00
            robust = pivot_wide[pivot_wide["robust"]].copy()
            print(f"\n  robust候補 (spread=0.5でPF≥1.00): {len(robust)}")
        else:
            robust = pd.DataFrame()

        # 保存
        robust_csv = os.path.join(ranked_dir, "m1_scalp_spread_robust.csv")
        pivot_wide.sort_values(sp05_col if sp05_col in pivot_wide.columns else "strategy_name",
                               ascending=False).to_csv(robust_csv, index=False, encoding="utf-8-sig")
        print(f"  保存: {robust_csv}")

        # spread耐性ランキング表示
        print(f"\n  --- Spread耐性ランキング TOP15 ---")
        show = pivot_wide.sort_values(sp05_col if sp05_col in pivot_wide.columns else pivot_wide.columns[1],
                                       ascending=False).head(15)
        for _, r in show.iterrows():
            cols = [c for c in pivot_wide.columns if c.startswith("pf_sp")]
            vals = "  ".join(f"{c}={r[c]:.3f}" for c in cols)
            rob = "ROBUST" if r.get("robust", False) else ""
            print(f"    {r['strategy_name'][:35]:35s}  {vals}  {rob}")

    # === Phase 5: 分析サマリー ===
    print(f"\n{'='*70}")
    print(f"  ECN M1スキャル分析")
    print(f"{'='*70}")

    st = df[df["trade_count"] >= 100].copy()
    st["pf"] = st["pf"].apply(_cap)

    if st.empty:
        print("  trades≥100のデータなし")
    else:
        # 1. 通貨別
        print(f"\n  --- 1. 通貨別ランキング ---")
        sg = st.groupby("symbol").agg(
            avg_pf=("pf", "mean"), med_pf=("pf", "median"), max_pf=("pf", "max"),
            avg_wr=("winrate", "mean"), avg_trades=("trade_count", "mean"),
            avg_hold=("avg_hold_min", "mean"), count=("pf", "count"),
            expl=("pf", lambda x: (x >= 1.00).sum()),
            strong=("pf", lambda x: (x >= 1.10).sum()),
        ).sort_values("avg_pf", ascending=False)
        for idx, r in sg.iterrows():
            print(f"    {idx}_M1  avgPF={r['avg_pf']:.3f}  medPF={r['med_pf']:.3f}  maxPF={r['max_pf']:.3f}  WR={r['avg_wr']:.1f}%  trades={r['avg_trades']:.0f}  hold={r['avg_hold']:.0f}m  PF≥1.0={r['expl']:.0f}  PF≥1.1={r['strong']:.0f}")

        # 2. RSI期間別
        print(f"\n  --- 2. RSI期間別ランキング ---")
        rg = st.groupby("rsi_period").agg(
            avg_pf=("pf", "mean"), med_pf=("pf", "median"),
            avg_wr=("winrate", "mean"), avg_trades=("trade_count", "mean"),
        ).sort_values("avg_pf", ascending=False)
        for idx, r in rg.iterrows():
            print(f"    RSI({idx})  avgPF={r['avg_pf']:.3f}  medPF={r['med_pf']:.3f}  WR={r['avg_wr']:.1f}%  trades={r['avg_trades']:.0f}")

        # 3. 閾値別
        print(f"\n  --- 3. 閾値別ランキング ---")
        tg = st.groupby("threshold").agg(
            avg_pf=("pf", "mean"), med_pf=("pf", "median"),
            avg_wr=("winrate", "mean"), avg_trades=("trade_count", "mean"),
        ).sort_values("avg_pf", ascending=False)
        for idx, r in tg.iterrows():
            print(f"    {idx:6s}  avgPF={r['avg_pf']:.3f}  medPF={r['med_pf']:.3f}  WR={r['avg_wr']:.1f}%  trades={r['avg_trades']:.0f}")

        # 4. TP/SL別
        print(f"\n  --- 4. TP/SL別ランキング ---")
        st["tp_sl"] = st["tp_display"] + "/" + st["sl_display"]
        tsg = st.groupby("tp_sl").agg(
            avg_pf=("pf", "mean"), med_pf=("pf", "median"),
            avg_wr=("winrate", "mean"), avg_trades=("trade_count", "mean"),
            count=("pf", "count"),
        ).sort_values("avg_pf", ascending=False)
        for idx, r in tsg.iterrows():
            print(f"    TP/SL={idx:8s}  avgPF={r['avg_pf']:.3f}  medPF={r['med_pf']:.3f}  WR={r['avg_wr']:.1f}%  trades={r['avg_trades']:.0f}  (n={r['count']:.0f})")

        # 5. LowVol効果
        print(f"\n  --- 5. LowVolフィルタ効果 ---")
        lg = st.groupby("has_lowvol").agg(
            avg_pf=("pf", "mean"), med_pf=("pf", "median"),
            avg_wr=("winrate", "mean"), avg_trades=("trade_count", "mean"),
        )
        for idx, r in lg.iterrows():
            label = "あり" if idx else "なし"
            print(f"    LowVol {label}  avgPF={r['avg_pf']:.3f}  medPF={r['med_pf']:.3f}  WR={r['avg_wr']:.1f}%  trades={r['avg_trades']:.0f}")

        # 6. セッション別
        print(f"\n  --- 6. セッション別 ---")
        ssg = st.groupby("session").agg(
            avg_pf=("pf", "mean"), avg_wr=("winrate", "mean"), avg_trades=("trade_count", "mean"),
        ).sort_values("avg_pf", ascending=False)
        for idx, r in ssg.iterrows():
            print(f"    {idx:10s}  avgPF={r['avg_pf']:.3f}  WR={r['avg_wr']:.1f}%  trades={r['avg_trades']:.0f}")

    # === 結論 ===
    print(f"\n{'='*70}")
    print(f"  結論")
    print(f"{'='*70}")

    if not st.empty:
        best_sym = sg.index[0] if not sg.empty else "?"
        best_rsi = rg.index[0] if not rg.empty else "?"
        best_th = tg.index[0] if not tg.empty else "?"
        best_tpsl = tsg.index[0] if not tsg.empty else "?"

        print(f"\n  1. M1スキャル最適通貨: {best_sym}")
        print(f"  2. 最良RSI期間: RSI({best_rsi})")
        print(f"  3. 最良閾値: {best_th}")
        print(f"  4. 最良TP/SL: {best_tpsl}")

        if sens_rows:
            # spread崩壊ポイント分析
            sp_avg = sens_df.groupby("spread_pips")["pf_capped"].mean()
            print(f"\n  5. Spread感応度 (全戦略平均PF):")
            for sp, pf in sp_avg.items():
                marker = " ← 基準" if abs(sp - 0.3) < 0.01 else ""
                broken = " [崩壊]" if pf < 1.0 else ""
                print(f"      spread={sp:.1f}pips  avgPF={pf:.3f}{marker}{broken}")

        n_expl = len(expl)
        n_strong = len(strong)
        n_robust = len(robust) if not robust.empty else 0

        print(f"\n  6. ECN前提で戦えるか:")
        print(f"      exploration候補: {n_expl}")
        print(f"      strong候補:      {n_strong}")
        print(f"      robust候補:      {n_robust}")

        if n_strong > 0:
            print(f"\n  → ECN口座 (spread 0.3pips + commission 0.5pips) なら")
            print(f"    M1スキャルで利益を出せる可能性がある。")
        elif n_expl > 0:
            print(f"\n  → 損益分岐付近の戦略は存在する。")
            print(f"    パラメータ最適化とフィルタ微調整で改善の余地あり。")
        else:
            print(f"\n  → ECN前提でも候補ゼロ。RSI単体のスキャルは困難。")
            print(f"    シグナル自体の改善 (複合シグナル等) が必要。")

    # サマリーファイル
    summary_path = os.path.join(results_dir, "m1_ecn_summary.txt")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(f"ECN M1スキャル探索結果\n{'='*50}\n")
        f.write(f"コスト: spread={spread*100:.1f}pips + commission={commission*2*100:.1f}pips = {cost_total:.1f}pips/trade\n")
        f.write(f"戦略数: {len(configs)}\n")
        f.write(f"テスト数: {len(all_results)}\n")
        f.write(f"exploration候補: {len(expl)}\n")
        f.write(f"strong候補: {len(strong)}\n")
    print(f"\n  サマリー: {summary_path}")

    print(f"\n{'='*70}")
    print(f"  実行コマンド (Windows)")
    print(f"{'='*70}")
    print(f"  cd fx_lab")
    print(f"  python main.py --scalp-ecn")
    print(f"{'='*70}")


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_dir)
    import yaml
    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler("logs/m1_ecn.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    with open(os.path.join("config", "settings.yaml"), "r", encoding="utf-8") as f:
        settings = yaml.safe_load(f)
    run_ecn_scalp(settings)
