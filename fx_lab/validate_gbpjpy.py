"""候補2 & 候補3 GBPJPY_M1限定 詳細検証

データ: 利用可能な全期間 (現在: 2025-01〜04, 2年データ入手後は自動対応)
対象: FXFactory_atr_break_02, FXFactory_hilo_break_03
通貨: GBPJPY_M1 限定

出力:
  1. 年別PF/PNL
  2. 月別PF/PNL
  3. 最大DD / 平均DD
  4. 最大連敗 / 連勝連敗分布
  5. expectancy
  6. trade数
  7. equity curve
  8. session別比較 (London / NewYork / London+NY)
  9. spread sensitivity (0.3, 0.5, 1.0)
  10. 最終判定 (A/B/C)
"""

import os, sys, logging
from collections import defaultdict, Counter
import pandas as pd, numpy as np

from engine.configurable_strategy import ConfigurableStrategy
from data_loader import load_ohlc
from metrics import evaluate_strategy
from engine.evolution import split_walk_forward, _classify_session

logger = logging.getLogger(__name__)

ECN_SP = 0.003; ECN_CM = 0.0025
SP_TESTS = [0.003, 0.005, 0.010]

CONFIGS = {
    "候補2: ATR Break P5M1.0 NY LV BE TR 120m": {
        "entry_signal": {"type":"atr_break","category":"breakout","period":5,"multiplier":1.0},
        "entry_filters": [{"type":"session_filter","session":"newyork"},{"type":"atr_low_vola_filter","lookback":60}],
        "exit_rules": {"tp_type":"atr_mult","tp_atr_mult":6.0,"sl_type":"atr_mult","sl_atr_mult":1.5,
                       "atr_period":10,"breakeven":True,"be_trigger_pips":0.03,"max_bars":120,
                       "trailing":True,"trail_type":"atr_mult","trail_atr_mult":0.7},
        "name": "FXFactory_atr_break_02",
    },
    "候補3: HiLo Break LB15 NY LV 120m": {
        "entry_signal": {"type":"hilo_break","category":"breakout","lookback":15,"confirm_bars":1},
        "entry_filters": [{"type":"session_filter","session":"newyork"},{"type":"atr_low_vola_filter","lookback":120}],
        "exit_rules": {"tp_type":"atr_mult","tp_atr_mult":5.0,"sl_type":"atr_mult","sl_atr_mult":1.5,
                       "atr_period":14,"max_bars":120},
        "name": "FXFactory_hilo_break_03",
    },
}

SESSIONS_TEST = {
    "london":    {"type":"session_filter","session":"london"},
    "newyork":   {"type":"session_filter","session":"newyork"},
    "london_ny": {"type":"session_filter","session":"london_ny"},
}


def _bt(cfg, df, bal, sp, cm):
    strat = ConfigurableStrategy(config=cfg, spread=sp, commission=cm)
    return strat.backtest(df, initial_balance=bal)


def _equity_curve(trades, bal):
    eq = [bal]
    peak = bal; dds = []; max_dd_abs = 0; max_dd_pct = 0
    for t in trades:
        eq.append(eq[-1] + t.pnl)
        if eq[-1] > peak: peak = eq[-1]
        dd = peak - eq[-1]
        ddp = dd / peak * 100 if peak > 0 else 0
        dds.append(dd)
        if dd > max_dd_abs: max_dd_abs = dd
        if ddp > max_dd_pct: max_dd_pct = ddp
    return eq, max_dd_abs, max_dd_pct, np.mean(dds) if dds else 0


def _streak_distribution(trades):
    """連勝/連敗の分布を計算"""
    if not trades: return {}, {}
    win_streaks = []; loss_streaks = []
    w = 0; l = 0
    for t in trades:
        if t.pnl > 0:
            w += 1
            if l > 0: loss_streaks.append(l); l = 0
        else:
            l += 1
            if w > 0: win_streaks.append(w); w = 0
    if w > 0: win_streaks.append(w)
    if l > 0: loss_streaks.append(l)
    return Counter(win_streaks), Counter(loss_streaks)


def _period_breakdown(trades, bal, fmt):
    groups = defaultdict(list)
    for t in trades:
        key = t.entry_time.strftime(fmt)
        groups[key].append(t)
    rows = []
    for k in sorted(groups):
        trs = groups[k]
        m = evaluate_strategy(trs, bal)
        _, mdd, mddp, avg_dd = _equity_curve(trs, bal)
        pf = m["pf"] if np.isfinite(m["pf"]) and m["pf"] < 100 else None
        rows.append({"period": k, "pf": pf, "pf_raw": m["pf"], "pnl": m["total_pnl"],
                      "wr": m["winrate"], "trades": m["trade_count"],
                      "exp": m["expectancy"], "max_dd": mdd, "max_dd_pct": mddp,
                      "max_closs": m["max_consecutive_losses"],
                      "max_cwin": m["max_consecutive_wins"],
                      "payoff": m["payoff_ratio"]})
    return rows


def _print_header(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def run_gbpjpy_validation(settings):
    bal = settings.get("initial_balance", 100000)
    ecn = settings.get("ecn", {})
    sp = ecn.get("spread", ECN_SP); cm = ecn.get("commission", ECN_CM)
    dd_dir = settings.get("data_dir", "data/raw")
    rd = settings.get("results_dir", "results")
    final_dir = os.path.join(rd, "final"); os.makedirs(final_dir, exist_ok=True)

    # データ読み込み
    data_path = os.path.join(dd_dir, "GBPJPY_M1.csv")
    df = load_ohlc(data_path)
    date_start = df["timestamp"].min()
    date_end = df["timestamp"].max()
    n_days = (date_end - date_start).days

    print(f"\n{'#'*70}")
    print(f"  候補2 & 候補3 GBPJPY_M1限定 詳細検証")
    print(f"{'#'*70}")
    print(f"  データ: {date_start.date()} 〜 {date_end.date()} ({n_days}日間, {len(df):,}本)")
    print(f"  ECN: spread={sp*100:.1f}pips + comm={cm*2*100:.1f}pips = {(sp+cm*2)*100:.1f}pips/trade")
    if n_days < 365:
        print(f"  ⚠ データ期間が{n_days}日 (<365日)。2年データ入手後に再実行を推奨。")

    all_csv_rows = []

    for label, cfg in CONFIGS.items():
        _print_header(label)

        trades = _bt(cfg, df, bal, sp, cm)
        m = evaluate_strategy(trades, bal)
        eq, max_dd, max_dd_pct, avg_dd = _equity_curve(trades, bal)
        wstreaks, lstreaks = _streak_distribution(trades)

        # === 全期間サマリー ===
        pf_s = f"{m['pf']:.3f}" if np.isfinite(m['pf']) and m['pf'] < 100 else "---"
        print(f"\n  【全期間】")
        print(f"  PF={pf_s}  WR={m['winrate']:.1f}%  trades={m['trade_count']}")
        print(f"  PNL={m['total_pnl']:.2f}  期待値={m['expectancy']:.4f}  ペイオフ={m['payoff_ratio']:.3f}")
        print(f"  最大DD={max_dd:.2f} ({max_dd_pct:.2f}%)  平均DD={avg_dd:.2f}")
        print(f"  最大連敗={m['max_consecutive_losses']}  最大連勝={m['max_consecutive_wins']}")
        print(f"  エクイティ: {eq[0]:.0f} → {eq[-1]:.0f}  min={min(eq):.0f}  max={max(eq):.0f}")

        # === 連勝/連敗分布 ===
        print(f"\n  【連勝/連敗分布】")
        print(f"  連勝分布: ", end="")
        for k in sorted(wstreaks): print(f"{k}連勝×{wstreaks[k]}", end="  ")
        print()
        print(f"  連敗分布: ", end="")
        for k in sorted(lstreaks): print(f"{k}連敗×{lstreaks[k]}", end="  ")
        print()

        # === 年別 ===
        yearly = _period_breakdown(trades, bal, "%Y")
        print(f"\n  【年別PF/PNL】")
        print(f"  {'年':6s}  {'PF':>7s}  {'WR':>6s}  {'trades':>6s}  {'PNL':>10s}  {'期待値':>8s}  {'最大DD':>8s}  {'最大連敗':>6s}")
        for r in yearly:
            pf = f"{r['pf']:.3f}" if r['pf'] is not None else "---"
            print(f"  {r['period']:6s}  {pf:>7s}  {r['wr']:5.1f}%  {r['trades']:6d}  {r['pnl']:+10.2f}  {r['exp']:+8.4f}  {r['max_dd']:8.2f}  {r['max_closs']:6d}")

        # === 月別 ===
        monthly = _period_breakdown(trades, bal, "%Y-%m")
        print(f"\n  【月別PF/PNL】")
        print(f"  {'月':8s}  {'PF':>7s}  {'WR':>6s}  {'trades':>6s}  {'PNL':>10s}  {'期待値':>8s}  {'最大連敗':>6s}  バー")
        pf_months = 0; total_months = 0
        for r in monthly:
            pf = f"{r['pf']:.3f}" if r['pf'] is not None else "---"
            bar = "+" * max(1, int(abs(r['pnl']) * 2)) if r['pnl'] > 0 else "-" * max(1, int(abs(r['pnl']) * 2))
            if len(bar) > 30: bar = bar[:30] + "..."
            print(f"  {r['period']:8s}  {pf:>7s}  {r['wr']:5.1f}%  {r['trades']:6d}  {r['pnl']:+10.2f}  {r['exp']:+8.4f}  {r['max_closs']:6d}  {bar}")
            if r['pf'] is not None:
                total_months += 1
                if r['pf'] >= 1.0: pf_months += 1
        if total_months > 0:
            print(f"  月別PF≥1.0: {pf_months}/{total_months} ({pf_months/total_months*100:.0f}%)")

        # === Session別 ===
        print(f"\n  【セッション別比較】")
        print(f"  {'session':12s}  {'PF':>7s}  {'WR':>6s}  {'trades':>6s}  {'PNL':>10s}  {'期待値':>8s}  {'最大連敗':>6s}  {'最大DD':>8s}")
        for sess_name, sess_filt in SESSIONS_TEST.items():
            new_cfg = dict(cfg)
            new_filters = [sess_filt] + [f for f in cfg.get("entry_filters", []) if f.get("type") != "session_filter"]
            new_cfg = {**cfg, "entry_filters": new_filters}
            sess_trades = _bt(new_cfg, df, bal, sp, cm)
            sm = evaluate_strategy(sess_trades, bal)
            _, smdd, smddp, _ = _equity_curve(sess_trades, bal)
            pf = f"{sm['pf']:.3f}" if np.isfinite(sm['pf']) and sm['pf'] < 100 else "---"
            print(f"  {sess_name:12s}  {pf:>7s}  {sm['winrate']:5.1f}%  {sm['trade_count']:6d}  {sm['total_pnl']:+10.2f}  {sm['expectancy']:+8.4f}  {sm['max_consecutive_losses']:6d}  {smdd:8.2f}")
            all_csv_rows.append({"strategy": cfg["name"], "session": sess_name,
                                 "pf": sm["pf"], "wr": sm["winrate"], "trades": sm["trade_count"],
                                 "pnl": sm["total_pnl"], "exp": sm["expectancy"],
                                 "max_closs": sm["max_consecutive_losses"], "max_dd": smdd})

        # === Spread感応度 ===
        print(f"\n  【Spread感応度】")
        print(f"  {'spread':>10s}  {'PF':>7s}  {'WR':>6s}  {'trades':>6s}  {'PNL':>10s}  {'期待値':>8s}")
        for sp_test in SP_TESTS:
            sp_trades = _bt(cfg, df, bal, sp_test, cm)
            spm = evaluate_strategy(sp_trades, bal)
            pf = f"{spm['pf']:.3f}" if np.isfinite(spm['pf']) and spm['pf'] < 100 else "---"
            cost = (sp_test + cm * 2) * 100
            print(f"  {sp_test*100:5.1f}pips ({cost:.1f}p)  {pf:>7s}  {spm['winrate']:5.1f}%  {spm['trade_count']:6d}  {spm['total_pnl']:+10.2f}  {spm['expectancy']:+8.4f}")

        # === WF月次ローリング ===
        print(f"\n  【月次ローリングWF】")
        df_copy = df.copy()
        df_copy["ym"] = df_copy["timestamp"].dt.to_period("M")
        months = sorted(df_copy["ym"].unique())
        wf_ok = 0; wf_total = 0
        for i in range(len(months) - 1):
            is_df = df_copy[df_copy["ym"] == months[i]].reset_index(drop=True)
            oos_df = df_copy[df_copy["ym"] == months[i+1]].reset_index(drop=True)
            if len(is_df) < 100 or len(oos_df) < 100: continue
            is_t = _bt(cfg, is_df, bal, sp, cm)
            oos_t = _bt(cfg, oos_df, bal, sp, cm)
            is_m = evaluate_strategy(is_t, bal)
            oos_m = evaluate_strategy(oos_t, bal)
            is_pf = min(is_m["pf"], 10) if np.isfinite(is_m["pf"]) else 0
            oos_pf = min(oos_m["pf"], 10) if np.isfinite(oos_m["pf"]) else 0
            judge = "★" if oos_pf >= 1.0 else "×"
            wf_total += 1
            if oos_pf >= 1.0: wf_ok += 1
            print(f"    IS={months[i]}→OOS={months[i+1]}  IS_PF={is_pf:.3f}  OOS_PF={oos_pf:.3f}  trades={oos_m['trade_count']}  {judge}")
        if wf_total > 0:
            print(f"    WF安定率: {wf_ok}/{wf_total} ({wf_ok/wf_total*100:.0f}%)")

        # === Equity Curve テキスト描画 ===
        print(f"\n  【エクイティカーブ】")
        n_points = min(50, len(eq))
        step = max(1, len(eq) // n_points)
        sampled = eq[::step]
        if sampled[-1] != eq[-1]: sampled.append(eq[-1])
        mn, mx = min(sampled), max(sampled)
        rng = mx - mn if mx > mn else 1
        width = 50
        for i, v in enumerate(sampled):
            pos = int((v - mn) / rng * width)
            bar = " " * pos + "█"
            pct = (i * step / len(eq) * 100) if i < len(sampled) - 1 else 100
            print(f"    {pct:5.0f}% {v:12.0f} |{bar}")

        # CSV用データ
        all_csv_rows.append({"strategy": cfg["name"], "session": "default",
                             "pf": m["pf"], "wr": m["winrate"], "trades": m["trade_count"],
                             "pnl": m["total_pnl"], "exp": m["expectancy"],
                             "max_closs": m["max_consecutive_losses"], "max_dd": max_dd,
                             "max_dd_pct": max_dd_pct, "avg_dd": avg_dd})

    # CSV保存
    pd.DataFrame(all_csv_rows).to_csv(os.path.join(final_dir, "gbpjpy_validation.csv"),
                                       index=False, encoding="utf-8-sig")

    # === 最終判定 ===
    _print_header("最終判定")
    for label, cfg in CONFIGS.items():
        trades = _bt(cfg, df, bal, sp, cm)
        m = evaluate_strategy(trades, bal)
        eq, max_dd, max_dd_pct, avg_dd = _equity_curve(trades, bal)
        monthly = _period_breakdown(trades, bal, "%Y-%m")
        mo_pfs = [r["pf"] for r in monthly if r["pf"] is not None]
        mo_pos = sum(1 for p in mo_pfs if p >= 1.0) / len(mo_pfs) * 100 if mo_pfs else 0

        # sp=0.5テスト
        sp05_trades = _bt(cfg, df, bal, 0.005, cm)
        sp05_m = evaluate_strategy(sp05_trades, bal)
        sp05_pf = sp05_m["pf"] if np.isfinite(sp05_m["pf"]) else 0

        pf = m["pf"] if np.isfinite(m["pf"]) else 0

        score = 0
        reasons = []

        # PF
        if pf >= 1.1:
            score += 3; reasons.append(f"PF={pf:.3f} ≥ 1.1 (優秀)")
        elif pf >= 1.0:
            score += 2; reasons.append(f"PF={pf:.3f} ≥ 1.0 (合格)")
        else:
            score += 0; reasons.append(f"PF={pf:.3f} < 1.0 (不合格)")

        # 月別安定性
        if mo_pos >= 70:
            score += 3; reasons.append(f"月別PF≥1.0率={mo_pos:.0f}% (安定)")
        elif mo_pos >= 50:
            score += 2; reasons.append(f"月別PF≥1.0率={mo_pos:.0f}% (まずまず)")
        elif mo_pos >= 30:
            score += 1; reasons.append(f"月別PF≥1.0率={mo_pos:.0f}% (不安定)")
        else:
            reasons.append(f"月別PF≥1.0率={mo_pos:.0f}% (悪い)")

        # trades数
        if m["trade_count"] >= 500:
            score += 2; reasons.append(f"trades={m['trade_count']} (十分)")
        elif m["trade_count"] >= 200:
            score += 1; reasons.append(f"trades={m['trade_count']} (少なめ)")
        else:
            reasons.append(f"trades={m['trade_count']} (不足)")

        # DD
        if max_dd_pct <= 5:
            score += 1; reasons.append(f"最大DD={max_dd_pct:.1f}% (低い)")
        elif max_dd_pct <= 15:
            score += 0; reasons.append(f"最大DD={max_dd_pct:.1f}% (中程度)")
        else:
            score -= 1; reasons.append(f"最大DD={max_dd_pct:.1f}% (危険)")

        # Spread耐性
        if sp05_pf >= 1.0:
            score += 2; reasons.append(f"sp=0.5pips PF={sp05_pf:.3f} ≥ 1.0 (頑健)")
        elif sp05_pf >= 0.9:
            score += 1; reasons.append(f"sp=0.5pips PF={sp05_pf:.3f} (やや脆弱)")
        else:
            reasons.append(f"sp=0.5pips PF={sp05_pf:.3f} (脆弱)")

        # データ期間ペナルティ
        if n_days < 365:
            score -= 2; reasons.append(f"データ{n_days}日 (<365日) -2点ペナルティ")

        # 判定
        if score >= 9:
            grade = "A: 即リアル可"
        elif score >= 5:
            grade = "B: デモフォワード必要"
        else:
            grade = "C: 再設計必要"

        print(f"\n  {label}")
        for r in reasons:
            print(f"    - {r}")
        print(f"    スコア: {score}/11")
        print(f"    >>> 判定: {grade} <<<")

    print(f"\n  保存: {os.path.join(final_dir, 'gbpjpy_validation.csv')}")
    print(f"\n  ⚠ 2年データ入手後、同じコマンドで再実行してください:")
    print(f"    cd fx_lab && python main.py --gbpjpy-validate")
    print(f"{'#'*70}")


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_dir)
    import yaml; os.makedirs("logs", exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.FileHandler("logs/gbpjpy_validate.log", encoding="utf-8"), logging.StreamHandler(sys.stdout)])
    with open(os.path.join("config", "settings.yaml"), "r", encoding="utf-8") as f:
        settings = yaml.safe_load(f)
    run_gbpjpy_validation(settings)
