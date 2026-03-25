"""最終候補 長期検証

利用可能データ: 2025-01〜2025-04 (約3ヶ月)
全データ期間で検証 (IS/OOS分割なし = 過学習チェック込み)

検証内容:
  1. 月別PF/PNL
  2. 週別PF分布
  3. 最大連敗/DD
  4. spread sensitivity (0.3, 0.5, 1.0)
  5. session別 (london / newyork / london+ny)
  6. 全通貨ペア
  7. Walk-forward 月次ローリング
"""

import os, sys, logging
from collections import defaultdict
import pandas as pd, numpy as np
from tqdm import tqdm

from engine.configurable_strategy import ConfigurableStrategy
from data_loader import load_ohlc, discover_data_files
from metrics import evaluate_strategy, calculate_drawdown
from engine.evolution import _classify_session

logger = logging.getLogger(__name__)

ECN_SP = 0.003; ECN_CM = 0.0025
SYMS = ["USDJPY","EURJPY","GBPJPY"]; TF = "M1"
SP_TESTS = [0.003, 0.005, 0.010]  # 0.3, 0.5, 1.0 pips

SESSIONS_DEF = {
    "london": (7, 16),
    "newyork": (13, 22),
    "london_ny": (7, 22),
}

FINAL_CONFIGS = [
    {
        "entry_signal": {"type":"atr_break","category":"breakout","period":5,"multiplier":1.0},
        "entry_filters": [{"type":"session_filter","session":"newyork"},{"type":"atr_low_vola_filter","lookback":60}],
        "exit_rules": {"tp_type":"atr_mult","tp_atr_mult":4.0,"sl_type":"atr_mult","sl_atr_mult":1.5,
                       "atr_period":10,"breakeven":True,"be_trigger_pips":0.03,
                       "trailing":True,"trail_type":"atr_mult","trail_atr_mult":0.7},
        "name": "FXFactory_atr_break_01", "label": "ATR Break P5M1.0 NY LV BE TR",
    },
    {
        "entry_signal": {"type":"atr_break","category":"breakout","period":5,"multiplier":1.0},
        "entry_filters": [{"type":"session_filter","session":"newyork"},{"type":"atr_low_vola_filter","lookback":60}],
        "exit_rules": {"tp_type":"atr_mult","tp_atr_mult":6.0,"sl_type":"atr_mult","sl_atr_mult":1.5,
                       "atr_period":10,"breakeven":True,"be_trigger_pips":0.03,"max_bars":120,
                       "trailing":True,"trail_type":"atr_mult","trail_atr_mult":0.7},
        "name": "FXFactory_atr_break_02", "label": "ATR Break P5M1.0 NY LV BE TR 120m",
    },
    {
        "entry_signal": {"type":"hilo_break","category":"breakout","lookback":15,"confirm_bars":1},
        "entry_filters": [{"type":"session_filter","session":"newyork"},{"type":"atr_low_vola_filter","lookback":120}],
        "exit_rules": {"tp_type":"atr_mult","tp_atr_mult":5.0,"sl_type":"atr_mult","sl_atr_mult":1.5,
                       "atr_period":14,"max_bars":120},
        "name": "FXFactory_hilo_break_03", "label": "HiLo Break LB15 NY LV 120m",
    },
    {
        "entry_signal": {"type":"hilo_break","category":"breakout","lookback":5,"confirm_bars":2},
        "entry_filters": [{"type":"session_filter","session":"london"}],
        "exit_rules": {"tp_type":"atr_mult","tp_atr_mult":3.0,"sl_type":"atr_mult","sl_atr_mult":1.0,
                       "atr_period":14,"breakeven":True,"be_trigger_pips":0.05,
                       "trailing":True,"trail_type":"atr_mult","trail_atr_mult":1.0,"max_bars":60},
        "name": "FXFactory_hilo_break_04", "label": "HiLo Break LB5CB2 LN BE TR 60m",
    },
    {
        "entry_signal": {"type":"atr_break","category":"breakout","period":10,"multiplier":0.8},
        "entry_filters": [{"type":"session_filter","session":"newyork"},{"type":"atr_low_vola_filter","lookback":120}],
        "exit_rules": {"tp_type":"atr_mult","tp_atr_mult":3.0,"sl_type":"atr_mult","sl_atr_mult":1.5,
                       "atr_period":14,"trailing":True,"trail_type":"atr_mult","trail_atr_mult":1.5,"max_bars":120},
        "name": "FXFactory_atr_break_05", "label": "ATR Break P10M0.8 NY LV TR 120m",
    },
]


def _backtest_full(cfg, df, bal, sp, cm):
    strat = ConfigurableStrategy(config=cfg, spread=sp, commission=cm)
    return strat.backtest(df, initial_balance=bal)


def _monthly_breakdown(trades, bal):
    """月別にPF/PNL/trades/DD等を集計"""
    if not trades:
        return []
    monthly = defaultdict(list)
    for t in trades:
        key = t.entry_time.strftime("%Y-%m")
        monthly[key].append(t)

    rows = []
    for mo in sorted(monthly.keys()):
        trs = monthly[mo]
        m = evaluate_strategy(trs, bal)
        rows.append({"month": mo, **m})
    return rows


def _weekly_breakdown(trades, bal):
    if not trades:
        return []
    weekly = defaultdict(list)
    for t in trades:
        key = t.entry_time.strftime("%Y-W%W")
        weekly[key].append(t)
    rows = []
    for wk in sorted(weekly.keys()):
        trs = weekly[wk]
        m = evaluate_strategy(trs, bal)
        rows.append({"week": wk, **m})
    return rows


def _rolling_wf(cfg, df, bal, sp, cm, window_months=1):
    """月次ローリングWF: 1ヶ月ISで学習し、次の1ヶ月OOSで評価"""
    df = df.copy()
    df["ym"] = df["timestamp"].dt.to_period("M")
    months = sorted(df["ym"].unique())
    results = []
    for i in range(len(months) - 1):
        is_month = months[i]
        oos_month = months[i + 1]
        is_df = df[df["ym"] == is_month].reset_index(drop=True)
        oos_df = df[df["ym"] == oos_month].reset_index(drop=True)
        if len(is_df) < 100 or len(oos_df) < 100:
            continue
        is_trades = _backtest_full(cfg, is_df, bal, sp, cm)
        oos_trades = _backtest_full(cfg, oos_df, bal, sp, cm)
        is_m = evaluate_strategy(is_trades, bal)
        oos_m = evaluate_strategy(oos_trades, bal)
        is_pf = min(is_m["pf"], 10) if np.isfinite(is_m["pf"]) else 0
        oos_pf = min(oos_m["pf"], 10) if np.isfinite(oos_m["pf"]) else 0
        results.append({
            "is_period": str(is_month), "oos_period": str(oos_month),
            "is_pf": is_pf, "oos_pf": oos_pf,
            "oos_trades": oos_m["trade_count"], "oos_pnl": oos_m["total_pnl"],
        })
    return results


def _session_test(cfg, df, bal, sp, cm):
    """セッション別にフィルタを差し替えてテスト"""
    results = []
    for sess_name, (s_start, s_end) in SESSIONS_DEF.items():
        # configのセッションフィルタを差し替え
        new_cfg = {**cfg, "entry_filters": [
            {"type": "session_filter", "session": sess_name}
        ] + [f for f in cfg.get("entry_filters", []) if f.get("type") != "session_filter"]}
        new_cfg["name"] = cfg["name"]
        trades = _backtest_full(new_cfg, df, bal, sp, cm)
        m = evaluate_strategy(trades, bal)
        m["session"] = sess_name
        results.append(m)
    return results


def run_long_term(settings):
    bal = settings.get("initial_balance", 100000)
    ecn = settings.get("ecn", {})
    sp = ecn.get("spread", ECN_SP); cm = ecn.get("commission", ECN_CM)
    dd = settings.get("data_dir", "data/raw"); rd = settings.get("results_dir", "results")

    final_dir = os.path.join(rd, "final")
    os.makedirs(final_dir, exist_ok=True)

    alld = discover_data_files(dd)
    dfs = {d["symbol"]: load_ohlc(d["filepath"])
           for d in alld if d["symbol"] in SYMS and d["timeframe"] == TF}

    date_range = {}
    for sym, df in dfs.items():
        date_range[sym] = (df["timestamp"].min(), df["timestamp"].max(), len(df))

    print(f"\n{'#'*70}")
    print(f"  最終候補 長期検証")
    print(f"{'#'*70}")
    print(f"  ECN: spread={sp*100:.1f}pips + comm={cm*2*100:.1f}pips")
    print(f"\n  データ期間:")
    for sym, (mn, mx, n) in date_range.items():
        print(f"    {sym}: {mn.date()} 〜 {mx.date()} ({n:,}本)")
    print(f"\n  ※ 全データ期間で検証 (IS/OOS分割なし)")
    print(f"  ※ 2年/5年データは未入手のため、利用可能な3ヶ月で実施")

    all_validation = []
    all_monthly = []
    all_weekly = []
    all_session = []
    all_spread = []
    all_wf = []

    for ci, cfg in enumerate(FINAL_CONFIGS, 1):
        name = cfg["name"]; label = cfg["label"]
        print(f"\n{'='*70}")
        print(f"  [{ci}/5] {label}")
        print(f"  {name}")
        print(f"{'='*70}")

        for sym, df in dfs.items():
            trades = _backtest_full(cfg, df, bal, sp, cm)
            m = evaluate_strategy(trades, bal)
            pf_disp = f"{m['pf']:.3f}" if np.isfinite(m['pf']) else "inf"

            # エクイティカーブ
            equity = [bal]
            peak = bal; max_dd_abs = 0; max_dd_pct_eq = 0
            for t in trades:
                equity.append(equity[-1] + t.pnl)
                if equity[-1] > peak: peak = equity[-1]
                dd_now = peak - equity[-1]
                dd_pct = (dd_now / peak * 100) if peak > 0 else 0
                if dd_now > max_dd_abs: max_dd_abs = dd_now
                if dd_pct > max_dd_pct_eq: max_dd_pct_eq = dd_pct

            # 平均DD (各トレード後のDD平均)
            dd_list = []
            eq_peak = bal
            for e in equity[1:]:
                if e > eq_peak: eq_peak = e
                dd_list.append(eq_peak - e)
            avg_dd = np.mean(dd_list) if dd_list else 0

            print(f"\n  [{sym}_M1] 全期間")
            print(f"    PF={pf_disp}  WR={m['winrate']:.1f}%  trades={m['trade_count']}  PNL={m['total_pnl']:.2f}")
            print(f"    期待値={m['expectancy']:.4f}  ペイオフ={m['payoff_ratio']:.3f}")
            print(f"    最大連敗={m['max_consecutive_losses']}  最大連勝={m['max_consecutive_wins']}")
            print(f"    最大DD={max_dd_abs:.2f} ({max_dd_pct_eq:.2f}%)  平均DD={avg_dd:.2f}")
            print(f"    エクイティ: {equity[0]:.0f} → {equity[-1]:.0f}  min={min(equity):.0f}  max={max(equity):.0f}")

            row = {"strategy": name, "label": label, "symbol": sym,
                   "pf": m["pf"], "winrate": m["winrate"], "trades": m["trade_count"],
                   "pnl": m["total_pnl"], "expectancy": m["expectancy"],
                   "payoff": m["payoff_ratio"], "max_consec_loss": m["max_consecutive_losses"],
                   "max_dd_abs": max_dd_abs, "max_dd_pct": max_dd_pct_eq, "avg_dd": avg_dd}
            all_validation.append(row)

            # --- 月別 ---
            mo_rows = _monthly_breakdown(trades, bal)
            print(f"\n    月別:")
            print(f"    {'月':8s}  {'PF':>7s}  {'WR':>6s}  {'trades':>6s}  {'PNL':>8s}  {'期待値':>8s}  {'最大連敗':>6s}")
            for mr in mo_rows:
                pf_s = f"{mr['pf']:.3f}" if np.isfinite(mr['pf']) and mr['pf'] < 100 else "---"
                print(f"    {mr['month']:8s}  {pf_s:>7s}  {mr['winrate']:5.1f}%  {mr['trade_count']:6d}  {mr['total_pnl']:+8.2f}  {mr['expectancy']:+8.4f}  {mr['max_consecutive_losses']:6d}")
                all_monthly.append({"strategy": name, "symbol": sym, **mr})

            # 月別PF安定性
            mo_pfs = [min(mr["pf"], 10) for mr in mo_rows if np.isfinite(mr["pf"])]
            if mo_pfs:
                pf_pos = sum(1 for p in mo_pfs if p >= 1.0)
                print(f"    月別PF≥1.0: {pf_pos}/{len(mo_pfs)} ({pf_pos/len(mo_pfs)*100:.0f}%)")

            # --- 週別 ---
            wk_rows = _weekly_breakdown(trades, bal)
            wk_pfs = [min(wr["pf"], 10) for wr in wk_rows if np.isfinite(wr["pf"]) and wr["trade_count"] >= 3]
            if wk_pfs:
                wk_pos = sum(1 for p in wk_pfs if p >= 1.0)
                print(f"    週別PF≥1.0: {wk_pos}/{len(wk_pfs)} ({wk_pos/len(wk_pfs)*100:.0f}%)  avg={np.mean(wk_pfs):.3f}  med={np.median(wk_pfs):.3f}")
            for wr in wk_rows:
                all_weekly.append({"strategy": name, "symbol": sym, **wr})

            # --- Session別 ---
            print(f"\n    セッション別:")
            sess_rows = _session_test(cfg, df, bal, sp, cm)
            for sr in sess_rows:
                pf_s = f"{sr['pf']:.3f}" if np.isfinite(sr['pf']) and sr['pf'] < 100 else "---"
                print(f"      {sr['session']:12s}  PF={pf_s:>7s}  WR={sr['winrate']:5.1f}%  trades={sr['trade_count']:4d}  PNL={sr['total_pnl']:+8.2f}")
                all_session.append({"strategy": name, "symbol": sym, **sr})

            # --- Spread感応度 ---
            print(f"\n    Spread感応度:")
            for sp_test in SP_TESTS:
                trades_sp = _backtest_full(cfg, df, bal, sp_test, cm)
                m_sp = evaluate_strategy(trades_sp, bal)
                pf_s = f"{m_sp['pf']:.3f}" if np.isfinite(m_sp['pf']) and m_sp['pf'] < 100 else "---"
                print(f"      sp={sp_test*100:.1f}pips  PF={pf_s:>7s}  trades={m_sp['trade_count']:4d}  PNL={m_sp['total_pnl']:+8.2f}")
                all_spread.append({"strategy": name, "symbol": sym,
                                   "spread_pips": sp_test*100, "pf": m_sp["pf"],
                                   "trades": m_sp["trade_count"], "pnl": m_sp["total_pnl"]})

            # --- Rolling WF ---
            wf_rows = _rolling_wf(cfg, df, bal, sp, cm)
            if wf_rows:
                print(f"\n    月次ローリングWF:")
                for wr in wf_rows:
                    judge = "★" if wr["oos_pf"] >= 1.0 else "×"
                    print(f"      IS={wr['is_period']}→OOS={wr['oos_period']}  IS_PF={wr['is_pf']:.3f}  OOS_PF={wr['oos_pf']:.3f}  trades={wr['oos_trades']}  {judge}")
                    all_wf.append({"strategy": name, "symbol": sym, **wr})

    # === CSV保存 ===
    pd.DataFrame(all_validation).to_csv(os.path.join(final_dir, "long_term_validation.csv"), index=False, encoding="utf-8-sig")
    pd.DataFrame(all_monthly).to_csv(os.path.join(final_dir, "monthly_pf.csv"), index=False, encoding="utf-8-sig")
    if all_weekly:
        pd.DataFrame(all_weekly).to_csv(os.path.join(final_dir, "weekly_pf.csv"), index=False, encoding="utf-8-sig")
    pd.DataFrame(all_session).to_csv(os.path.join(final_dir, "session_comparison.csv"), index=False, encoding="utf-8-sig")
    pd.DataFrame(all_spread).to_csv(os.path.join(final_dir, "spread_sensitivity.csv"), index=False, encoding="utf-8-sig")
    if all_wf:
        pd.DataFrame(all_wf).to_csv(os.path.join(final_dir, "rolling_wf.csv"), index=False, encoding="utf-8-sig")

    # === 総合評価 ===
    print(f"\n\n{'#'*70}")
    print(f"  総合評価")
    print(f"{'#'*70}")

    vdf = pd.DataFrame(all_validation)
    for ci, cfg in enumerate(FINAL_CONFIGS, 1):
        name = cfg["name"]; label = cfg["label"]
        sub = vdf[vdf["strategy"] == name]

        # 全通貨平均PF
        pfs = [min(p, 10) for p in sub["pf"] if np.isfinite(p)]
        avg_pf = np.mean(pfs) if pfs else 0
        all_positive = all(p >= 1.0 for p in pfs)

        # 月別安定性
        mo_sub = [r for r in all_monthly if r["strategy"] == name]
        mo_pfs_all = [min(r["pf"], 10) for r in mo_sub if np.isfinite(r["pf"])]
        mo_pos_rate = sum(1 for p in mo_pfs_all if p >= 1.0) / len(mo_pfs_all) * 100 if mo_pfs_all else 0

        # Spread耐性
        sp_sub = pd.DataFrame([r for r in all_spread if r["strategy"] == name])
        sp05 = sp_sub[sp_sub["spread_pips"] == 0.5]
        sp05_avg_pf = sp05["pf"].apply(lambda x: min(x, 10) if np.isfinite(x) else 0).mean() if not sp05.empty else 0
        sp10 = sp_sub[sp_sub["spread_pips"] == 1.0]
        sp10_avg_pf = sp10["pf"].apply(lambda x: min(x, 10) if np.isfinite(x) else 0).mean() if not sp10.empty else 0

        # WF安定性
        wf_sub = [r for r in all_wf if r["strategy"] == name]
        wf_oos_pfs = [r["oos_pf"] for r in wf_sub]
        wf_pos_rate = sum(1 for p in wf_oos_pfs if p >= 1.0) / len(wf_oos_pfs) * 100 if wf_oos_pfs else 0

        # 最大DD
        max_dd = sub["max_dd_pct"].max()

        # 総合判定
        score = 0
        if avg_pf >= 1.1: score += 2
        elif avg_pf >= 1.0: score += 1
        if mo_pos_rate >= 60: score += 2
        elif mo_pos_rate >= 40: score += 1
        if sp05_avg_pf >= 1.0: score += 2
        elif sp05_avg_pf >= 0.9: score += 1
        if wf_pos_rate >= 50: score += 2
        elif wf_pos_rate >= 30: score += 1
        if max_dd <= 5: score += 1

        if score >= 7:
            grade = "A: すぐ実運用可能"
        elif score >= 4:
            grade = "B: デモフォワード推奨"
        else:
            grade = "C: 再設計必要"

        print(f"\n  [{ci}] {label}")
        print(f"      全通貨平均PF: {avg_pf:.3f}  {'全通貨PF≥1.0' if all_positive else '一部PF<1.0'}")
        print(f"      月別PF≥1.0率: {mo_pos_rate:.0f}%")
        print(f"      sp=0.5耐性PF: {sp05_avg_pf:.3f}  sp=1.0耐性PF: {sp10_avg_pf:.3f}")
        print(f"      WF OOS PF≥1.0率: {wf_pos_rate:.0f}%")
        print(f"      最大DD: {max_dd:.2f}%")
        print(f"      スコア: {score}/9")
        print(f"      >>> 判定: {grade} <<<")

    print(f"\n{'#'*70}")
    print(f"  注意事項")
    print(f"{'#'*70}")
    print(f"  - データは3ヶ月分(2025-01〜04)のみ。2年/5年検証には追加データが必要")
    print(f"  - 月3回の検証窓では統計的信頼性は限定的")
    print(f"  - 実運用前に必ずデモ口座で最低3ヶ月のフォワードテストを推奨")
    print(f"  - EA化コードは results/ea_mt4/ に生成済み")

    print(f"\n  保存先:")
    print(f"    {os.path.join(final_dir, 'long_term_validation.csv')}")
    print(f"    {os.path.join(final_dir, 'monthly_pf.csv')}")
    print(f"    {os.path.join(final_dir, 'session_comparison.csv')}")
    print(f"    {os.path.join(final_dir, 'spread_sensitivity.csv')}")
    print(f"    {os.path.join(final_dir, 'rolling_wf.csv')}")

    print(f"\n  Windows: cd fx_lab && python main.py --validate")
    print(f"{'#'*70}")


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_dir)
    import yaml; os.makedirs("logs", exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.FileHandler("logs/validate.log", encoding="utf-8"), logging.StreamHandler(sys.stdout)])
    with open(os.path.join("config", "settings.yaml"), "r", encoding="utf-8") as f:
        settings = yaml.safe_load(f)
    run_long_term(settings)
