"""1コマンドで fetch → opt → WFA → report を完走する自動化パイプライン.

Usage:
    # 合成データで全シンボル
    python3 backtest/full_pipeline.py --symbols BTCUSDT,ETHUSDT,DOGEUSDT,XRPUSDT \\
        --tf 15 --days 365 --fee 0.04

    # 実データ (Bitget API 必要、サンドボックス外で実行)
    python3 backtest/full_pipeline.py --symbols BTCUSDT --tf 15 --days 365 \\
        --fetch-real --fee 0.04

成果物:
    results/<sym>_top10.json         - 全期間グリッドのトップ10
    results/<sym>_walkforward.json   - WFA OOS 各fold結果
    results/<sym>_best.set           - MT5用パラメータ
    results/full_report.md           - 横並び比較レポート (Markdown)
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

from optimize import score, write_set_file
from strategy import Params, backtest

REPO = Path(__file__).resolve().parent.parent

# トレンド向けフォーカスグリッド
TREND_GRID = dict(
    ema_fast        = [20, 34],
    ema_slow        = [100, 200],
    atr_min_mult    = [0.8, 1.2],
    tp_atr_mult     = [6.0, 10.0],
    sl_atr_mult     = [1.0, 1.5],
    trail_start_atr = [1.0, 2.0],
    trail_step_atr  = [0.5, 1.0],
    adx_min         = [0.0, 25.0, 30.0],
    htf_ratio       = [0, 4],
    trail_only      = [False, True],
)


# ----------------------------- pipeline steps -----------------------------

def step_fetch_or_generate(symbols: list[str], tf_min: int, days: int,
                           use_real: bool) -> dict[str, Path]:
    """データ取得/生成. 戻り値: symbol -> CSV path."""
    out_paths: dict[str, Path] = {}
    if use_real:
        from bitget_public import BitgetPublic, BitgetConfig
        cli = BitgetPublic(BitgetConfig(product_type="spot"))
        end_iso = pd.Timestamp.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
        start_iso = (pd.Timestamp.utcnow() - pd.Timedelta(days=days)).strftime(
            "%Y-%m-%dT%H:%M:%S")
        tf_str = {1: "1m", 5: "5m", 15: "15m", 60: "1h",
                  240: "4h", 1440: "1d"}.get(tf_min, f"{tf_min}m")
    for sym in symbols:
        if use_real:
            out_path = REPO / f"data/{sym.lower()}_{tf_min}m.csv"
            if not out_path.exists():
                print(f"[fetch] {sym} {tf_str} {days}d ...", flush=True)
                cli.download_and_save(sym, tf_str, start_iso, end_iso, out_path)
            out_paths[sym] = out_path
        else:
            out_path = REPO / f"data/{sym.lower()}_{tf_min}m_synth.csv"
            if not out_path.exists():
                cmd = [sys.executable, "backtest/synth_data.py",
                       "--symbol", sym, "--tf", str(tf_min),
                       "--days", str(days), "--out", str(out_path)]
                print(f"[synth] {sym} ...", flush=True)
                r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
                if r.returncode != 0:
                    print(r.stdout); print(r.stderr, file=sys.stderr)
                    raise SystemExit(f"synth failed for {sym}")
            out_paths[sym] = out_path
    return out_paths


def iter_params(base: Params):
    keys = list(TREND_GRID.keys())
    for combo in itertools.product(*[TREND_GRID[k] for k in keys]):
        kw = dict(zip(keys, combo))
        if kw["ema_fast"] >= kw["ema_slow"]:
            continue
        yield replace(base, rsi_buy_min=55.0, rsi_sell_max=45.0, **kw)


def run_grid(df: pd.DataFrame, base: Params, top_k: int = 10) -> list[dict]:
    rows = []
    for p in iter_params(base):
        m = backtest(df, p).metrics()
        m["score"] = round(score(m), 4)
        m["params"] = {k: getattr(p, k) for k in
                       list(TREND_GRID.keys()) + ["rsi_buy_min", "rsi_sell_max"]}
        rows.append(m)
    rows.sort(key=lambda x: x["score"], reverse=True)
    return rows[:top_k]


def walk_forward(df: pd.DataFrame, base: Params, n_folds: int = 3) -> list[dict]:
    n = len(df)
    fold = n // (n_folds + 1)
    out = []
    for k in range(n_folds):
        is_end = fold * (k + 1)
        oos_end = fold * (k + 2)
        is_df = df.iloc[:is_end]
        oos_df = df.iloc[is_end:oos_end]
        if len(is_df) < 500 or len(oos_df) < 200:
            continue
        top = run_grid(is_df, base, top_k=1)
        if not top:
            continue
        best = top[0]
        rsi_kw = {k: best["params"][k] for k in ("rsi_buy_min", "rsi_sell_max")}
        grid_kw = {k: best["params"][k] for k in TREND_GRID.keys()}
        p_best = replace(base, **rsi_kw, **grid_kw)
        oos = backtest(oos_df, p_best).metrics()
        oos["score"] = round(score(oos), 4)
        oos["params"] = best["params"]
        oos["fold"] = k + 1
        oos["is_score"] = best["score"]
        out.append(oos)
    return out


def step_optimize(sym: str, csv: Path, base: Params, n_folds: int) -> dict:
    print(f"\n========== {sym} ==========", flush=True)
    df = pd.read_csv(csv, parse_dates=["time"]).set_index("time")
    print(f"  bars={len(df)}  range={df['close'].min():.6g}-{df['close'].max():.6g}",
          flush=True)

    is_top = run_grid(df, base, top_k=10)
    is_best = is_top[0]

    wf = walk_forward(df, base, n_folds=n_folds)
    oos_pf = [x["pf"] for x in wf if math.isfinite(x["pf"])]
    oos_ret = [x["ret"] for x in wf]

    summary = dict(
        symbol=sym,
        is_pf=is_best["pf"], is_ret=is_best["ret"], is_dd=is_best["max_dd"],
        is_n=is_best["n"], is_win=is_best["win"],
        oos_avg_pf=round(sum(oos_pf)/len(oos_pf), 3) if oos_pf else None,
        oos_avg_ret=round(sum(oos_ret)/len(oos_ret), 3) if oos_ret else None,
        oos_pfs=[round(x, 3) for x in oos_pf],
        best_params=is_best["params"],
    )
    print(f"  IS  pf={summary['is_pf']} ret={summary['is_ret']}% n={summary['is_n']}"
          f" win={summary['is_win']}%")
    print(f"  OOS pfs={summary['oos_pfs']} avg={summary['oos_avg_pf']}"
          f" ret={summary['oos_avg_ret']}%")

    out_dir = REPO / "results"
    suffix = sym.lower()
    (out_dir / f"top10_{suffix}_pipe.json").write_text(
        json.dumps(is_top, indent=2, default=str))
    (out_dir / f"walkforward_{suffix}_pipe.json").write_text(
        json.dumps(wf, indent=2, default=str))
    write_set_file(is_best["params"], out_dir / f"best_{suffix}_pipe.set")
    return summary


# ----------------------------- report -----------------------------

def step_report(rows: list[dict], tf_min: int, days: int,
                fee: float, slip: float, use_real: bool) -> Path:
    """Markdown レポートを生成."""
    out = REPO / "results" / "full_report.md"
    lines = [
        f"# Full Pipeline Report",
        f"",
        f"- TF: M{tf_min}",
        f"- Period: {days} days",
        f"- Fee (RT): {fee}% / Slippage: {slip}%",
        f"- Data source: {'**REAL (Bitget API)**' if use_real else '合成 (synth)'}",
        f"- Symbols: {', '.join(r['symbol'] for r in rows)}",
        f"",
        f"## Cross-symbol summary",
        f"",
        f"| Symbol | IS PF | IS ret% | IS n | IS win% | **OOS avg PF** | OOS PFs | OOS avg ret% |",
        f"|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        oos_pf = f"{r['oos_avg_pf']:.2f}" if r['oos_avg_pf'] is not None else "—"
        oos_ret = f"{r['oos_avg_ret']:.2f}" if r['oos_avg_ret'] is not None else "—"
        lines.append(
            f"| **{r['symbol']}** | {r['is_pf']:.2f} | {r['is_ret']:.2f} | "
            f"{r['is_n']} | {r['is_win']:.1f} | **{oos_pf}** | "
            f"{r['oos_pfs']} | {oos_ret} |"
        )
    lines += [
        f"",
        f"## Best params per symbol",
        f"",
    ]
    for r in rows:
        p = r["best_params"]
        lines.append(f"### {r['symbol']}")
        lines.append("```")
        for k, v in p.items():
            lines.append(f"{k:18s} = {v}")
        lines.append("```")
        lines.append("")
    lines += [
        f"## 注意",
        f"",
        f"- {'実データ' if use_real else '**合成データ**'}での結果。"
        f"{'本番判断に使えますが OOS 値の解釈に注意。' if use_real else '実データでの再最適化必須。'}",
        f"- WFA は 3-fold で OOS 1 fold ≈ {days // 4} 日。",
        f"- OOS PF > 1 が安定すればロバスト, < 1 は過剰最適化のサイン。",
    ]
    out.write_text("\n".join(lines))
    print(f"\nReport saved -> {out}")
    return out


# ----------------------------- main -----------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="BTCUSDT,ETHUSDT,DOGEUSDT,XRPUSDT",
                    help="comma-separated")
    ap.add_argument("--tf", type=int, default=15, help="TF minutes (5/15/60)")
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--fee", type=float, default=0.04,
                    help="RT fee% (Bitget maker=0.04, taker=0.12)")
    ap.add_argument("--slip", type=float, default=0.01)
    ap.add_argument("--folds", type=int, default=3)
    ap.add_argument("--risk-pct", type=float, default=0.5)
    ap.add_argument("--fetch-real", action="store_true",
                    help="Bitget API から実データ取得 (sandbox 外で実行)")
    args = ap.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",")]
    print(f"Pipeline: {symbols}  TF=M{args.tf}  days={args.days}  "
          f"fee={args.fee}%  data={'REAL' if args.fetch_real else 'synth'}")

    paths = step_fetch_or_generate(symbols, args.tf, args.days, args.fetch_real)
    base = Params(fee_rt_pct=args.fee, slippage_pct=args.slip,
                  risk_pct=args.risk_pct, fixed_qty=0.01)

    rows = []
    for sym in symbols:
        if sym in paths:
            rows.append(step_optimize(sym, paths[sym], base, args.folds))

    (REPO / "results" / "full_pipeline_summary.json").write_text(
        json.dumps(rows, indent=2, default=str))

    step_report(rows, args.tf, args.days, args.fee, args.slip, args.fetch_real)
    print("\nDone.")


if __name__ == "__main__":
    main()
