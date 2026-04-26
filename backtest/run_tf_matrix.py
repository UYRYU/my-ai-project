"""TF×手数料の比較最適化を順次実行して結果テーブルを書き出す.

注: 個別run より速く回すため、optimize.py の GRID を一時的に縮小して呼ぶ.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

# (tag, csv, fee_rt%, slip%, folds)
RUNS = [
    ("m15_taker", "data/btcusdt_15m_synth.csv", 0.12, 0.02, 3),
    ("m15_maker", "data/btcusdt_15m_synth.csv", 0.04, 0.01, 3),
    ("h1_taker",  "data/btcusdt_1h_synth.csv",  0.12, 0.02, 3),
    ("h1_maker",  "data/btcusdt_1h_synth.csv",  0.04, 0.01, 3),
]

REPO = Path(__file__).resolve().parent.parent


def run(cmd: list[str]):
    print("$", " ".join(cmd))
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout); print(r.stderr, file=sys.stderr)
        raise SystemExit(r.returncode)
    return r.stdout


def summarize_run(tag: str) -> dict:
    out_dir = REPO / "results"
    top = json.loads((out_dir / f"top10_{tag}.json").read_text())
    wf  = json.loads((out_dir / f"walkforward_{tag}.json").read_text())
    is_best = top[0]
    oos_pf = [x["pf"] for x in wf if math.isfinite(x["pf"])]
    oos_ret = [x["ret"] for x in wf]
    return {
        "tag": tag,
        "is_pf": is_best["pf"],
        "is_ret": is_best["ret"],
        "is_dd": is_best["max_dd"],
        "is_win": is_best["win"],
        "is_n": is_best["n"],
        "oos_avg_pf": round(sum(oos_pf) / len(oos_pf), 3) if oos_pf else None,
        "oos_avg_ret": round(sum(oos_ret) / len(oos_ret), 3) if oos_ret else None,
        "oos_pfs": [round(x, 3) for x in oos_pf],
        "best_params": is_best["params"],
    }


def main():
    for tag, csv, fee, slip, folds in RUNS:
        print(f"\n========== {tag} ==========")
        run([
            sys.executable, "backtest/optimize.py",
            "--csv", csv,
            "--out", "results",
            "--fee", str(fee),
            "--slip", str(slip),
            "--tag", tag,
            "--folds", str(folds),
            "--quick",  # GRID 縮小版で高速回す
        ])

    print("\n\n=========== Summary ===========")
    rows = []
    for tag, *_ in RUNS:
        rows.append(summarize_run(tag))
    (REPO / "results" / "tf_fee_matrix.json").write_text(
        json.dumps(rows, indent=2, default=str))
    print(f"{'tag':12s}  IS_PF  IS_ret%  IS_DD%  OOS_PF  OOS_ret%   OOS_pfs")
    print("-" * 75)
    for r in rows:
        print(f"{r['tag']:12s}  {r['is_pf']:5.2f}  {r['is_ret']:7.2f}  "
              f"{r['is_dd']:6.2f}  {r['oos_avg_pf']:5.2f}  {r['oos_avg_ret']:8.2f}   "
              f"{r['oos_pfs']}")
    print(f"\nSaved -> results/tf_fee_matrix.json")


if __name__ == "__main__":
    main()
