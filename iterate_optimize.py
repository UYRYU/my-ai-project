"""Iterative optimizer that keeps refining until improvement stalls.

Phases (each is a focused grid search; each phase inherits the best
combo from prior phases for non-swept axes):

    1. expand   -- broaden the axes the first sweep didn't cover
                   (exit_on_sign_flip, stake_mode, finer edge / window).
    2. refine   -- neighbour search around phase-1 winner.
    3. risk     -- portfolio gates (concurrency, exposure, per-event,
                   daily loss).
    4. drift    -- non-zero risk-neutral drift + TTM windowing.
    5. robust   -- replay top-K candidates on multiple synthetic seeds;
                   pick the most stable winner, not just the highest.

Termination:
    Stop early if a phase fails to improve the best Sharpe by
    >= MIN_IMPROVEMENT (0.05) AND fails to improve total PnL by
    >= MIN_PNL_IMPROVEMENT ($100). Otherwise run all phases.

Outputs (under out/):
    iterative_history.csv  -- one row per (phase, combo) trial
    iterative_best.json    -- the final best combo + summary
    iterative.log          -- streaming progress
"""

from __future__ import annotations

import argparse
import itertools
import json
import logging
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd

from bs_edge.config import Config
from bs_edge.market_loader import UpDownMarket
from bs_edge.metrics import summarise
from bs_edge.portfolio import run_portfolio
from bs_edge.resolution import BinanceCloseResolver

# Reuse the synthetic universe builder from optimize.py.
from optimize import make_bars, make_markets_and_histories  # noqa: E402

MIN_IMPROVEMENT = 0.05
MIN_PNL_IMPROVEMENT = 100.0

# ---------------------------------------------------------------------------
# Combo plumbing
# ---------------------------------------------------------------------------


DEFAULT_COMBO: dict[str, Any] = {
    # Sigma
    "sigma_window_min": 240,
    "sigma_estimator": "close_to_close",
    # Edge / exit
    "edge_threshold": 0.12,
    "exit_edge_threshold": None,
    "exit_on_sign_flip": True,
    "exit_min_ttm_s": 60,
    # Stake
    "stake_mode": "flat",
    "flat_stake": 50.0,
    "kelly_fraction": 0.5,
    "kelly_cap": 0.25,
    # Slippage
    "slippage_model": "constant",
    "half_spread": 0.002,
    "impact_per_dollar": 5e-5,
    # Risk gates
    "max_concurrent_positions": 5,
    "max_notional_exposure": 1000.0,
    "per_event_notional_cap": 300.0,
    "daily_loss_limit": -500.0,
    # Drift / TTM
    "drift_override": None,
    "min_time_to_expiry_s": 60,
    "max_time_to_expiry_s": 24 * 3600,
}


def build_cfg(combo: dict[str, Any]) -> Config:
    return Config(
        sigma_windows_min=(combo["sigma_window_min"],),
        sigma_estimators=(combo["sigma_estimator"],),
        edge_threshold=combo["edge_threshold"],
        exit_edge_threshold=combo["exit_edge_threshold"],
        exit_on_sign_flip=combo["exit_on_sign_flip"],
        min_time_to_expiry_s=combo["min_time_to_expiry_s"],
        exit_min_ttm_s=combo["exit_min_ttm_s"],
        max_time_to_expiry_s=combo["max_time_to_expiry_s"],
        max_concurrent_positions=combo["max_concurrent_positions"],
        max_notional_exposure=combo["max_notional_exposure"],
        per_event_notional_cap=combo["per_event_notional_cap"],
        daily_loss_limit=combo["daily_loss_limit"],
        flat_stake=combo["flat_stake"],
        stake_mode=combo["stake_mode"],
        kelly_fraction=combo["kelly_fraction"],
        kelly_cap=combo["kelly_cap"],
        slippage_model=combo["slippage_model"],
        half_spread=combo["half_spread"],
        impact_per_dollar=combo["impact_per_dollar"],
        drift_override=combo["drift_override"],
    )


def evaluate(
    combo: dict[str, Any],
    markets: list[UpDownMarket],
    bars: pd.DataFrame,
    histories: dict[str, pd.DataFrame],
    resolver: BinanceCloseResolver,
) -> dict[str, Any]:
    cfg = build_cfg(combo)
    port = run_portfolio(
        markets, bars, histories, cfg,
        sigma_window_min=combo["sigma_window_min"],
        sigma_estimator=combo["sigma_estimator"],
        resolver=resolver,
    )
    s = summarise(port.to_frame())
    return {**combo, **asdict(s), "blocks": json.dumps(dict(port.blocked_by_gate))}


# ---------------------------------------------------------------------------
# Phase definitions
# ---------------------------------------------------------------------------


def _grid(axes: dict[str, Iterable[Any]], base: dict[str, Any]) -> list[dict[str, Any]]:
    keys = list(axes.keys())
    values = [list(axes[k]) for k in keys]
    out = []
    for combo_vals in itertools.product(*values):
        c = dict(base)
        c.update(dict(zip(keys, combo_vals)))
        out.append(c)
    return out


def phase_1_expand(best: dict[str, Any]) -> list[dict[str, Any]]:
    return _grid({
        "sigma_window_min": [120, 240, 360, 720],
        "sigma_estimator": ["close_to_close", "parkinson", "yang_zhang"],
        "edge_threshold": [0.08, 0.10, 0.12, 0.15, 0.20],
        "exit_edge_threshold": [None, 0.01, 0.02],
        "exit_on_sign_flip": [True, False],
        "stake_mode": ["flat", "kelly"],
    }, best)


def phase_2_refine(best: dict[str, Any]) -> list[dict[str, Any]]:
    sw = best["sigma_window_min"]
    edge = best["edge_threshold"]
    return _grid({
        "sigma_window_min": sorted({max(60, sw - 60), sw, sw + 60, sw + 120}),
        "edge_threshold": sorted({max(0.02, edge - 0.03), max(0.02, edge - 0.01),
                                  edge, edge + 0.01, edge + 0.03}),
        "exit_edge_threshold": [None, 0.005, 0.01, 0.015, 0.02],
        "kelly_fraction": ([0.25, 0.5, 0.75, 1.0]
                            if best["stake_mode"] == "kelly" else [best["kelly_fraction"]]),
        "kelly_cap": ([0.10, 0.25, 0.5]
                       if best["stake_mode"] == "kelly" else [best["kelly_cap"]]),
        "flat_stake": ([25.0, 50.0, 100.0, 200.0]
                       if best["stake_mode"] == "flat" else [best["flat_stake"]]),
    }, best)


def phase_3_risk(best: dict[str, Any]) -> list[dict[str, Any]]:
    return _grid({
        "max_concurrent_positions": [3, 5, 8, 12, 20],
        "per_event_notional_cap": [150.0, 300.0, 500.0, 1000.0, 5000.0],
        "max_notional_exposure": [500.0, 1000.0, 2000.0, 5000.0],
        "daily_loss_limit": [-200.0, -500.0, -1000.0, -10_000.0],
    }, best)


def phase_4_drift(best: dict[str, Any]) -> list[dict[str, Any]]:
    return _grid({
        "drift_override": [None, -0.2, -0.1, 0.0, 0.1, 0.2, 0.5],
        "min_time_to_expiry_s": [30, 60, 120, 300],
        "max_time_to_expiry_s": [3600, 6 * 3600, 24 * 3600],
    }, best)


def phase_5_robust(top_combos: list[dict[str, Any]], n_seeds: int = 5) -> list[tuple[dict, int]]:
    out = []
    for seed in range(101, 101 + n_seeds):
        for c in top_combos:
            c2 = dict(c)
            c2["__seed__"] = seed
            out.append(c2)
    return out  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


@dataclass
class State:
    best_combo: dict[str, Any]
    best_sharpe: float = -math.inf
    best_pnl: float = -math.inf
    history: list[dict[str, Any]] = field(default_factory=list)


def _brief(c: dict[str, Any]) -> str:
    return (
        f"sw={c.get('sigma_window_min')} est={str(c.get('sigma_estimator'))[:3]} "
        f"edge={c.get('edge_threshold'):.2f} xex={c.get('exit_edge_threshold')} "
        f"flip={'Y' if c.get('exit_on_sign_flip') else 'N'} "
        f"stk={c.get('stake_mode')} hs={c.get('half_spread'):.3f} "
        f"slip={c.get('slippage_model')} maxc={c.get('max_concurrent_positions')} "
        f"pec={c.get('per_event_notional_cap')} drift={c.get('drift_override')}"
    )


def run_phase(
    name: str, combos: list[dict[str, Any]], state: State,
    universe: tuple[list[UpDownMarket], pd.DataFrame, dict[str, pd.DataFrame], BinanceCloseResolver],
    log: logging.Logger,
) -> tuple[float, float]:
    markets, bars, histories, resolver = universe
    log.info("=== PHASE %s :: %d combos ===", name.upper(), len(combos))
    rows = []
    t0 = time.time()
    phase_best_sharpe = -math.inf
    phase_best_pnl = -math.inf
    phase_best_combo = None
    for i, combo in enumerate(combos, 1):
        try:
            row = evaluate(combo, markets, bars, histories, resolver)
        except Exception as exc:
            log.error("combo %d failed: %s", i, exc)
            continue
        row["phase"] = name
        rows.append(row)
        if row["sharpe"] > phase_best_sharpe:
            phase_best_sharpe = row["sharpe"]
            phase_best_pnl = row["total_pnl"]
            phase_best_combo = combo
        if i % 25 == 0 or i == len(combos):
            log.info(
                "[%s %d/%d %.1fs] phase_best Sharpe=%.2f PnL=%.1f  global Sharpe=%.2f",
                name, i, len(combos), time.time() - t0,
                phase_best_sharpe, phase_best_pnl, state.best_sharpe,
            )
    state.history.extend(rows)
    if phase_best_combo is not None and (
        phase_best_sharpe > state.best_sharpe + MIN_IMPROVEMENT
        or phase_best_pnl > state.best_pnl + MIN_PNL_IMPROVEMENT
    ):
        delta_s = phase_best_sharpe - state.best_sharpe
        delta_p = phase_best_pnl - state.best_pnl
        log.info(
            "  IMPROVED: Sharpe %.2f -> %.2f (+%.2f), PnL %.1f -> %.1f (+%.1f)",
            state.best_sharpe, phase_best_sharpe, delta_s,
            state.best_pnl, phase_best_pnl, delta_p,
        )
        state.best_sharpe = phase_best_sharpe
        state.best_pnl = phase_best_pnl
        state.best_combo = phase_best_combo
        return delta_s, delta_p
    log.info(
        "  NO MATERIAL IMPROVEMENT (Sharpe %.2f vs best %.2f, PnL %.1f vs best %.1f)",
        phase_best_sharpe, state.best_sharpe, phase_best_pnl, state.best_pnl,
    )
    return phase_best_sharpe - state.best_sharpe, phase_best_pnl - state.best_pnl


def evaluate_robust(
    combos_top: list[dict[str, Any]], n_seeds: int, n_days: int, n_markets: int,
    log: logging.Logger,
) -> dict[str, Any]:
    """Replay each candidate on multiple synthetic universes and pick the
    one whose mean - stdev Sharpe is highest (most stable winner)."""
    n_minutes = n_days * 24 * 60
    scores: dict[int, list[float]] = {}
    pnls: dict[int, list[float]] = {}
    for seed in range(101, 101 + n_seeds):
        bars = make_bars(n_minutes, seed=seed)
        markets, hist = make_markets_and_histories(
            bars, n_markets=n_markets, seed=seed + 1000,
        )
        resolver = BinanceCloseResolver(bars)
        for idx, c in enumerate(combos_top):
            row = evaluate(c, markets, bars, hist, resolver)
            scores.setdefault(idx, []).append(row["sharpe"])
            pnls.setdefault(idx, []).append(row["total_pnl"])
            log.info(
                "  seed=%d cand=%d Sharpe=%.2f PnL=%.1f", seed, idx,
                row["sharpe"], row["total_pnl"],
            )
    best_idx = -1
    best_score = -math.inf
    for idx, sh in scores.items():
        sh = np.array(sh)
        score = sh.mean() - sh.std(ddof=1)  # mean - 1 std penalty
        log.info(
            "  cand=%d mean Sharpe=%.2f stdev=%.2f score=%.2f mean PnL=%.1f",
            idx, sh.mean(), sh.std(ddof=1), score, np.mean(pnls[idx]),
        )
        if score > best_score:
            best_score = score
            best_idx = idx
    return {
        "best_combo": combos_top[best_idx],
        "robust_score": best_score,
        "mean_sharpe": float(np.mean(scores[best_idx])),
        "stdev_sharpe": float(np.std(scores[best_idx], ddof=1)),
        "mean_pnl": float(np.mean(pnls[best_idx])),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--n-days", type=int, default=14)
    p.add_argument("--n-markets", type=int, default=240)
    p.add_argument("--bars-seed", type=int, default=42)
    p.add_argument("--markets-seed", type=int, default=13)
    p.add_argument("--out-dir", type=Path, default=Path("out"))
    args = p.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(args.out_dir / "iterative.log", mode="w")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[fh, sh])
    log = logging.getLogger("iter")
    # Quiet the engine's per-run banner.
    logging.getLogger("bs_edge.portfolio").setLevel(logging.WARNING)

    log.info("building primary synthetic universe (%dd, %d markets)",
             args.n_days, args.n_markets)
    bars = make_bars(args.n_days * 24 * 60, seed=args.bars_seed)
    markets, histories = make_markets_and_histories(
        bars, n_markets=args.n_markets, seed=args.markets_seed,
    )
    resolver = BinanceCloseResolver(bars)
    universe = (markets, bars, histories, resolver)
    log.info("universe ready: %d markets, %d bars", len(markets), len(bars))

    state = State(best_combo=dict(DEFAULT_COMBO))
    log.info("seeding baseline: %s", _brief(state.best_combo))
    base_row = evaluate(state.best_combo, markets, bars, histories, resolver)
    state.best_sharpe = base_row["sharpe"]
    state.best_pnl = base_row["total_pnl"]
    state.history.append({**base_row, "phase": "baseline"})
    log.info("baseline Sharpe=%.2f PnL=%.1f", state.best_sharpe, state.best_pnl)

    consecutive_no_improve = 0
    phases: list[tuple[str, Callable[[dict[str, Any]], list[dict[str, Any]]]]] = [
        ("expand", phase_1_expand),
        ("refine", phase_2_refine),
        ("risk", phase_3_risk),
        ("drift", phase_4_drift),
        ("refine2", phase_2_refine),  # second refinement after drift / risk
    ]

    for name, builder in phases:
        combos = builder(state.best_combo)
        delta_s, delta_p = run_phase(name, combos, state, universe, log)
        if delta_s < MIN_IMPROVEMENT and delta_p < MIN_PNL_IMPROVEMENT:
            consecutive_no_improve += 1
        else:
            consecutive_no_improve = 0
        if consecutive_no_improve >= 2:
            log.info("two consecutive non-improving phases -- stopping early")
            break

    # Phase 5: robustness across seeds for the top candidates.
    top_k = (
        pd.DataFrame(state.history)
        .sort_values("sharpe", ascending=False)
        .drop_duplicates(subset=[c for c in DEFAULT_COMBO.keys() if c not in {"flat_stake"}])
        .head(5)
    )
    top_combos = [
        {k: row[k] for k in DEFAULT_COMBO.keys()} for _, row in top_k.iterrows()
    ]
    log.info("=== PHASE ROBUST :: %d candidates x 5 seeds ===", len(top_combos))
    robust = evaluate_robust(top_combos, n_seeds=5,
                             n_days=args.n_days, n_markets=args.n_markets, log=log)
    log.info(
        "robust winner: mean Sharpe=%.2f +/- %.2f, mean PnL=%.1f, score=%.2f",
        robust["mean_sharpe"], robust["stdev_sharpe"], robust["mean_pnl"],
        robust["robust_score"],
    )
    log.info("robust winner combo: %s", _brief(robust["best_combo"]))

    # Persist outputs.
    pd.DataFrame(state.history).to_csv(args.out_dir / "iterative_history.csv", index=False)
    final = {
        "single_seed_best": {
            "combo": state.best_combo,
            "sharpe": state.best_sharpe,
            "total_pnl": state.best_pnl,
        },
        "robust_best": {
            "combo": robust["best_combo"],
            "mean_sharpe": robust["mean_sharpe"],
            "stdev_sharpe": robust["stdev_sharpe"],
            "mean_pnl": robust["mean_pnl"],
            "score": robust["robust_score"],
        },
    }
    (args.out_dir / "iterative_best.json").write_text(json.dumps(final, indent=2, default=str))
    log.info("results written to %s/", args.out_dir)
    log.info("DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
