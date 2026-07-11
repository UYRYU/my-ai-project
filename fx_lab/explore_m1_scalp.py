"""M1スキャルピング探索 - A案

本来のスキャルEA構造に戻す:
  - M1 (1分足)
  - RSI短期 (5〜7), 閾値浅め (33〜38 / 62〜67)
  - 固定pips TP/SL (スプレッドの3〜10倍)
  - LowVolフィルタのみ (前回最有力)
  - trades 1000+ でPF評価
  - 保有時間 1〜15分目標
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
# スキャル設計パラメータ
# ================================================================

TARGET_SYMBOLS = ["GBPJPY", "USDJPY"]
TARGET_TIMEFRAME = "M1"
TARGET_SESSIONS = ["london", "newyork"]

# 評価基準 (スキャルらしくtrades重視)
EVAL_MIN_PF = 1.10
EVAL_MAX_DD = 15.0
EVAL_MIN_TRADES = 500

# --- RSI短期設定 ---
RSI_PERIODS = [5, 6, 7]
ENTRY_THRESHOLDS = [
    (33, 67),
    (35, 65),
    (37, 63),
    (38, 62),
]

# --- TP/SL: 固定pips (JPYペア: 0.01 = 1銭 ≈ 1pip) ---
# スプレッド0.02(2pips)に対してTP=3〜8pips, SL=3〜8pips
TP_CONFIGS = [
    {"tp_type": "fixed", "tp_pips": 0.03},   # 3pips
    {"tp_type": "fixed", "tp_pips": 0.05},   # 5pips
    {"tp_type": "fixed", "tp_pips": 0.08},   # 8pips
    {"tp_type": "fixed", "tp_pips": 0.10},   # 10pips
]

SL_CONFIGS = [
    {"sl_type": "fixed", "sl_pips": 0.03},   # 3pips
    {"sl_type": "fixed", "sl_pips": 0.05},   # 5pips
    {"sl_type": "fixed", "sl_pips": 0.08},   # 8pips
    {"sl_type": "fixed", "sl_pips": 0.10},   # 10pips
]

# --- 時間切れ: スキャルなので短め ---
MAX_BARS_OPTIONS = [
    {},                    # なし
    {"max_bars": 10},      # 10分
    {"max_bars": 15},      # 15分
    {"max_bars": 30},      # 30分
]

# --- 建値移動 ---
BREAKEVEN_OPTIONS = [
    {},
    {"breakeven": True, "be_trigger_pips": 0.02},   # 2pips利乗せで建値
    {"breakeven": True, "be_trigger_pips": 0.03},   # 3pips
]

# --- フィルタ: LowVolのみ (前回最有力) + なし ---
FILTER_OPTIONS = [
    [],                                                       # なし
    [{"type": "atr_low_vola_filter", "lookback": 30}],       # 30分中央値
    [{"type": "atr_low_vola_filter", "lookback": 60}],       # 60分中央値
    [{"type": "atr_low_vola_filter", "lookback": 120}],      # 120分中央値
]

ATR_PERIODS = [7, 10, 14]


def _generate_scalp_configs(target_count: int = 100) -> list[dict]:
    """M1スキャル戦略を体系的に生成"""
    random.seed(777)

    session_filters = [
        [{"type": "session_filter", "session": "london"}],
        [{"type": "session_filter", "session": "newyork"}],
    ]

    configs = []
    seen_hashes = set()

    # 全コア組み合わせ
    core_combos = list(itertools.product(
        RSI_PERIODS,
        ENTRY_THRESHOLDS,
        TP_CONFIGS,
        SL_CONFIGS,
        ATR_PERIODS,
    ))
    random.shuffle(core_combos)

    attempts = 0
    combo_idx = 0
    max_attempts = target_count * 20

    while len(configs) < target_count and attempts < max_attempts:
        attempts += 1
        if combo_idx >= len(core_combos):
            combo_idx = 0
            random.shuffle(core_combos)

        rsi_period, (oversold, overbought), tp_cfg, sl_cfg, atr_period = core_combos[combo_idx]
        combo_idx += 1

        sess = random.choice(session_filters)
        filt = random.choice(FILTER_OPTIONS)
        be_opt = random.choice(BREAKEVEN_OPTIONS)
        mb_opt = random.choice(MAX_BARS_OPTIONS)

        all_filters = sess + filt

        exit_rules = {
            **tp_cfg,
            **sl_cfg,
            "atr_period": atr_period,
            **be_opt,
            **mb_opt,
        }

        config = {
            "entry_signal": {
                "type": "rsi_reversal",
                "category": "mean_reversion",
                "period": rsi_period,
                "oversold": oversold,
                "overbought": overbought,
            },
            "entry_filters": all_filters,
            "exit_rules": exit_rules,
        }
        config["name"] = _make_name(config)

        cfg_hash = hashlib.md5(
            json.dumps(config, sort_keys=True, default=str).encode()
        ).hexdigest()
        if cfg_hash not in seen_hashes:
            seen_hashes.add(cfg_hash)
            configs.append(config)

    logger.info(f"M1スキャル戦略を {len(configs)} 個生成")
    return configs


def _describe_config(cfg: dict) -> dict:
    """configから主要パラメータを抽出"""
    sig = cfg["entry_signal"]
    rules = cfg["exit_rules"]
    filters = cfg.get("entry_filters", [])

    info = {
        "rsi_period": sig["period"],
        "oversold": sig["oversold"],
        "overbought": sig["overbought"],
        "tp_pips": rules.get("tp_pips", 0),
        "sl_pips": rules.get("sl_pips", 0),
        "tp_type": rules.get("tp_type", "?"),
        "sl_type": rules.get("sl_type", "?"),
        "has_breakeven": bool(rules.get("breakeven")),
        "max_bars": rules.get("max_bars", 0),
        "has_lowvol": False,
        "lowvol_lb": 0,
        "session": "all",
    }
    for f in filters:
        ft = f.get("type", "")
        if ft == "session_filter":
            info["session"] = f.get("session", "all")
        elif ft == "atr_low_vola_filter":
            info["has_lowvol"] = True
            info["lowvol_lb"] = f.get("lookback", 0)

    # TP/SLをpips表示用
    info["tp_display"] = f"{info['tp_pips']*100:.0f}p" if info["tp_type"] == "fixed" else "atr"
    info["sl_display"] = f"{info['sl_pips']*100:.0f}p" if info["sl_type"] == "fixed" else "atr"

    return info


def _run_oos_backtest(
    configs: list[dict],
    data_files: list[dict],
    initial_balance: float,
    spread: float,
    commission: float,
    is_ratio: float = 0.7,
) -> list[dict]:
    """OOSバックテスト"""
    results = []
    total = len(configs) * len(data_files)

    with tqdm(total=total, desc="  M1スキャルOOSテスト") as pbar:
        for data_info in data_files:
            symbol = data_info["symbol"]
            timeframe = data_info["timeframe"]

            try:
                df = load_ohlc(data_info["filepath"])
                _, oos_df = split_is_oos(df, is_ratio=is_ratio)
            except Exception as e:
                logger.error(f"データ読み込み失敗: {symbol}_{timeframe}: {e}")
                pbar.update(len(configs))
                continue

            for cfg in configs:
                try:
                    strat = ConfigurableStrategy(
                        config=cfg, spread=spread, commission=commission
                    )
                    trades = strat.backtest(oos_df, initial_balance=initial_balance)
                    result = evaluate_strategy(trades, initial_balance)
                    result["strategy_name"] = cfg["name"]
                    result["symbol"] = symbol
                    result["timeframe"] = timeframe

                    info = _describe_config(cfg)
                    result.update(info)

                    result["avg_hold_min"] = round(result["avg_holding_seconds"] / 60, 1)

                    # セッション別
                    if trades:
                        sp = {"tokyo": 0.0, "london": 0.0, "newyork": 0.0}
                        sc = {"tokyo": 0, "london": 0, "newyork": 0}
                        for t in trades:
                            s = _classify_session(t.entry_time.hour)
                            sp[s] += t.pnl
                            sc[s] += 1
                        for k in sp:
                            result[f"pnl_{k}"] = round(sp[k], 2)
                            result[f"trades_{k}"] = sc[k]
                    else:
                        for k in ["tokyo", "london", "newyork"]:
                            result[f"pnl_{k}"] = 0.0
                            result[f"trades_{k}"] = 0

                    results.append(result)
                except Exception as e:
                    logger.error(f"バックテスト失敗 ({cfg['name']}, {symbol}_{timeframe}): {e}")
                finally:
                    pbar.update(1)

    return results


def _cap_pf(v: float, cap: float = 10.0) -> float:
    if v == float("inf") or v != v:
        return cap
    return min(v, cap)


def run_m1_scalp_exploration(settings: dict) -> None:
    """M1スキャル探索メイン"""
    initial_balance = settings.get("initial_balance", 100000)
    spread = settings.get("spread", 0.02)
    commission = settings.get("commission", 0.005)
    data_dir = settings.get("data_dir", "data/raw")
    results_dir = settings.get("results_dir", "results")
    is_ratio = settings.get("research", {}).get("is_ratio", 0.7)

    ranked_dir = os.path.join(results_dir, "ranked")
    os.makedirs(ranked_dir, exist_ok=True)

    all_data = discover_data_files(data_dir)
    data_files = [
        d for d in all_data
        if d["symbol"] in TARGET_SYMBOLS and d["timeframe"] == TARGET_TIMEFRAME
    ]
    if not data_files:
        logger.error("対象データなし")
        return

    print(f"\n{'='*70}")
    print(f"  M1 スキャルピング探索 (A案)")
    print(f"{'='*70}")
    print(f"  時間足: M1  /  RSI(5-7) 閾値33-38/62-67")
    print(f"  TP: 3-10pips固定  /  SL: 3-10pips固定")
    print(f"  フィルタ: LowVol or なし")
    print(f"  対象: {', '.join(TARGET_SYMBOLS)}")
    print(f"  セッション: {', '.join(TARGET_SESSIONS)}")
    print(f"  スプレッド: {spread} ({spread*100:.0f}pips)")
    print(f"  評価: PF≥{EVAL_MIN_PF}, DD≤{EVAL_MAX_DD}%, trades≥{EVAL_MIN_TRADES}")

    # Phase 1: 生成
    print(f"\n  Phase 1: M1スキャル戦略生成...")
    configs = _generate_scalp_configs(target_count=100)
    print(f"  生成: {len(configs)} 個")

    rsi_dist = Counter(c["entry_signal"]["period"] for c in configs)
    th_dist = Counter((c["entry_signal"]["oversold"], c["entry_signal"]["overbought"]) for c in configs)
    lv_dist = Counter(any(f.get("type") == "atr_low_vola_filter" for f in c.get("entry_filters", [])) for c in configs)
    print(f"  RSI期間: {dict(rsi_dist)}")
    print(f"  閾値: {dict(th_dist)}")
    print(f"  LowVol: あり={lv_dist.get(True,0)} なし={lv_dist.get(False,0)}")

    # Phase 2: OOS
    total = len(configs) * len(data_files)
    print(f"\n  Phase 2: OOSバックテスト ({len(configs)} × {len(data_files)} = {total})")
    all_results = _run_oos_backtest(
        configs, data_files, initial_balance, spread, commission, is_ratio=is_ratio,
    )
    print(f"  結果: {len(all_results)}")
    if not all_results:
        print("  結果なし。終了。")
        return

    df = pd.DataFrame(all_results)
    df.to_csv(os.path.join(results_dir, "m1_scalp_all.csv"), index=False, encoding="utf-8-sig")

    # Phase 3: 候補抽出
    print(f"\n  Phase 3: 候補抽出 (PF≥{EVAL_MIN_PF}, DD≤{EVAL_MAX_DD}%, trades≥{EVAL_MIN_TRADES})")
    finite = np.isfinite(df["pf"])
    cand = df[
        finite
        & (df["pf"] >= EVAL_MIN_PF)
        & (df["max_dd_pct"] <= EVAL_MAX_DD)
        & (df["trade_count"] >= EVAL_MIN_TRADES)
    ].copy().sort_values("pf", ascending=False).reset_index(drop=True)
    print(f"  候補: {len(cand)}")

    cand_csv = os.path.join(ranked_dir, "m1_scalp_candidates.csv")
    cand.to_csv(cand_csv, index=False, encoding="utf-8-sig")
    print(f"  保存: {cand_csv}")

    if not cand.empty:
        print(f"\n  --- M1スキャル候補 TOP20 ---")
        for i, (_, r) in enumerate(cand.head(20).iterrows(), 1):
            lv = "LV" if r.get("has_lowvol") else "--"
            mb = f"{r['max_bars']}m" if r.get("max_bars", 0) > 0 else "--"
            be = "BE" if r.get("has_breakeven") else "--"
            print(f"    {i:2d}. {r['symbol']}_{r['timeframe']} [{r['session']:8s}]  PF={r['pf']:.3f}  WR={r['winrate']:.1f}%  DD={r['max_dd_pct']:.1f}%  trades={r['trade_count']:4.0f}  hold={r['avg_hold_min']:.0f}m  TP={r['tp_display']} SL={r['sl_display']}  RSI({r['rsi_period']}) {r['oversold']}/{r['overbought']}  [{lv} {be} {mb}]")

    # Phase 4: 分析
    print(f"\n{'='*70}")
    print(f"  M1スキャル分析")
    print(f"{'='*70}")

    # trades >= 100で統計
    st = df[df["trade_count"] >= 100].copy()
    st["pf"] = st["pf"].apply(_cap_pf)

    if st.empty:
        print("  trades≥100のデータなし")
    else:
        # 通貨 × セッション
        print(f"\n  --- 通貨 × セッション (trades≥100) ---")
        ps = st.groupby(["symbol", "session"]).agg(
            avg_pf=("pf", "mean"), med_pf=("pf", "median"),
            max_pf=("pf", "max"), avg_wr=("winrate", "mean"),
            avg_trades=("trade_count", "mean"),
            avg_hold=("avg_hold_min", "mean"),
            count=("pf", "count"),
            pf_ok=("pf", lambda x: (x >= EVAL_MIN_PF).sum()),
        ).sort_values("avg_pf", ascending=False)
        for (sym, sess), r in ps.iterrows():
            print(f"    {sym}_M1 [{sess:8s}]  avgPF={r['avg_pf']:.3f}  medPF={r['med_pf']:.3f}  maxPF={r['max_pf']:.3f}  WR={r['avg_wr']:.1f}%  trades={r['avg_trades']:.0f}  hold={r['avg_hold']:.0f}m  PF≥{EVAL_MIN_PF}={r['pf_ok']:.0f}/{r['count']:.0f}")

        # RSI期間
        print(f"\n  --- RSI期間別 ---")
        rg = st.groupby("rsi_period").agg(
            avg_pf=("pf", "mean"), avg_wr=("winrate", "mean"), avg_trades=("trade_count", "mean"),
        ).sort_values("avg_pf", ascending=False)
        for idx, r in rg.iterrows():
            print(f"    RSI({idx})  PF={r['avg_pf']:.3f}  WR={r['avg_wr']:.1f}%  trades={r['avg_trades']:.0f}")

        # 閾値
        print(f"\n  --- RSI閾値別 ---")
        st["threshold"] = st["oversold"].astype(str) + "/" + st["overbought"].astype(str)
        tg = st.groupby("threshold").agg(
            avg_pf=("pf", "mean"), avg_wr=("winrate", "mean"), avg_trades=("trade_count", "mean"),
        ).sort_values("avg_pf", ascending=False)
        for idx, r in tg.iterrows():
            print(f"    {idx:6s}  PF={r['avg_pf']:.3f}  WR={r['avg_wr']:.1f}%  trades={r['avg_trades']:.0f}")

        # TP/SL組み合わせ
        print(f"\n  --- TP/SL組み合わせ別 ---")
        st["tp_sl"] = st["tp_display"] + "/" + st["sl_display"]
        tsg = st.groupby("tp_sl").agg(
            avg_pf=("pf", "mean"), avg_wr=("winrate", "mean"),
            avg_trades=("trade_count", "mean"), count=("pf", "count"),
        ).sort_values("avg_pf", ascending=False).head(10)
        for idx, r in tsg.iterrows():
            print(f"    TP/SL={idx:8s}  PF={r['avg_pf']:.3f}  WR={r['avg_wr']:.1f}%  trades={r['avg_trades']:.0f}  (n={r['count']:.0f})")

        # LowVol効果
        print(f"\n  --- LowVolフィルタ効果 ---")
        lg = st.groupby("has_lowvol").agg(
            avg_pf=("pf", "mean"), med_pf=("pf", "median"),
            avg_wr=("winrate", "mean"), avg_trades=("trade_count", "mean"),
        )
        for idx, r in lg.iterrows():
            label = "あり" if idx else "なし"
            print(f"    LowVol {label}  avgPF={r['avg_pf']:.3f}  medPF={r['med_pf']:.3f}  WR={r['avg_wr']:.1f}%  trades={r['avg_trades']:.0f}")

        # 時間切れ効果
        print(f"\n  --- 時間切れ設定別 ---")
        mg = st.groupby("max_bars").agg(
            avg_pf=("pf", "mean"), avg_hold=("avg_hold_min", "mean"),
            avg_trades=("trade_count", "mean"),
        ).sort_values("avg_pf", ascending=False)
        for idx, r in mg.iterrows():
            label = f"{idx}分" if idx > 0 else "なし"
            print(f"    時間切れ {label:5s}  PF={r['avg_pf']:.3f}  hold={r['avg_hold']:.0f}m  trades={r['avg_trades']:.0f}")

        # 建値移動
        print(f"\n  --- 建値移動効果 ---")
        bg = st.groupby("has_breakeven").agg(
            avg_pf=("pf", "mean"), avg_wr=("winrate", "mean"),
        )
        for idx, r in bg.iterrows():
            label = "あり" if idx else "なし"
            print(f"    建値 {label}  PF={r['avg_pf']:.3f}  WR={r['avg_wr']:.1f}%")

    # サマリー保存
    summary_path = os.path.join(results_dir, "m1_scalp_summary.txt")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(f"M1スキャル探索結果\n{'='*50}\n")
        f.write(f"戦略数: {len(configs)}\n")
        f.write(f"テスト数: {len(all_results)}\n")
        f.write(f"候補数 (PF≥{EVAL_MIN_PF}, DD≤{EVAL_MAX_DD}%, trades≥{EVAL_MIN_TRADES}): {len(cand)}\n")
    print(f"\n  サマリー: {summary_path}")


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_dir)

    import yaml
    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler("logs/m1_scalp.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    with open(os.path.join("config", "settings.yaml"), "r", encoding="utf-8") as f:
        settings = yaml.safe_load(f)

    run_m1_scalp_exploration(settings)
