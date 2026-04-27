"""M1 BTC で taker/maker の最適化を回す."""
from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

RUNS = [
    ("m1_taker", "data/btcusdt_1m_synth.csv", 0.12, 0.02, 3),
    ("m1_maker", "data/btcusdt_1m_synth.csv", 0.04, 0.01, 3),
]
REPO = Path(__file__).resolve().parent.parent


def run(cmd: list[str]):
    print("$", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout); print(r.stderr, file=sys.stderr)
        raise SystemExit(r.returncode)
    return r.stdout


def summarize(tag: str) -> dict:
    out_dir = REPO / "results"
    top = json.loads((out_dir / f"top10_{tag}.json").read_text())
    wf  = json.loads((out_dir / f"walkforward_{tag}.json").read_text())
    is_best = top[0]
    oos_pf = [x["pf"] for x in wf if math.isfinite(x["pf"])]
    oos_ret = [x["ret"] for x in wf]
    return dict(tag=tag, is_pf=is_best["pf"], is_ret=is_best["ret"],
                is_dd=is_best["max_dd"], is_n=is_best["n"],
                oos_avg_pf=round(sum(oos_pf)/len(oos_pf), 3) if oos_pf else None,
                oos_avg_ret=round(sum(oos_ret)/len(oos_ret), 3) if oos_ret else None,
                oos_pfs=[round(x, 3) for x in oos_pf],
                best_params=is_best["params"])


def main():
    for tag, csv, fee, slip, folds in RUNS:
        print(f"\n========== {tag} ==========", flush=True)
        run([sys.executable, "backtest/optimize.py",
             "--csv", csv, "--out", "results",
             "--fee", str(fee), "--slip", str(slip),
             "--tag", tag, "--folds", str(folds), "--quick"])

    rows = [summarize(tag) for tag, *_ in RUNS]
    Path(REPO / "results" / "m1_matrix.json").write_text(
        json.dumps(rows, indent=2, default=str))
    print(f"\n{'tag':10s}  IS_PF  IS_ret%  IS_n  OOS_PF  OOS_ret%  OOS_pfs")
    print("-" * 70)
    for r in rows:
        print(f"{r['tag']:10s}  {r['is_pf']:5.2f}  {r['is_ret']:7.2f}  "
              f"{r['is_n']:4d}  {r['oos_avg_pf']:5.2f}  {r['oos_avg_ret']:8.2f}  "
              f"{r['oos_pfs']}")


if __name__ == "__main__":
    main()
