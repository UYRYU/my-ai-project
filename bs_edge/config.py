"""Configuration for the Black-Scholes edge detector.

All tunables live here. Nothing related to sigma windows, edge thresholds,
or fees is hard-coded anywhere else in the package.

Loader precedence: defaults -> optional YAML/JSON file -> environment
variables (prefix ``BSEDGE_``). Values from later sources override earlier
ones. This keeps the dataclass the single source of truth while allowing
walk-forward runs to sweep parameters without editing code.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PKG_ROOT = Path(__file__).resolve().parent
DEFAULT_CACHE_DIR = PKG_ROOT / "cache"


@dataclass
class Config:
    """Parameters for pricing, vol estimation, and backtesting.

    All times are expressed in *years* for Black-Scholes compatibility.
    Probabilities and prices are in [0, 1] (Polymarket convention).
    """

    # --- Volatility estimation -------------------------------------------------
    # Candidate windows (in minutes of 1m BTC bars) used by walk-forward.
    sigma_windows_min: tuple[int, ...] = (30, 60, 120, 240, 480, 1440)
    # Estimator family. One of {"close_to_close", "parkinson", "ewma",
    # "yang_zhang"}. Walk-forward may sweep across this list.
    sigma_estimators: tuple[str, ...] = ("close_to_close", "parkinson", "ewma")
    # EWMA decay (RiskMetrics-style) when estimator == "ewma".
    ewma_lambda: float = 0.94
    # Annualisation factor for minute bars (365 * 24 * 60).
    minutes_per_year: int = 365 * 24 * 60
    # Floor on sigma to prevent numerical blow-ups.
    sigma_floor_annual: float = 0.05

    # --- Pricing ---------------------------------------------------------------
    # Risk-free rate in continuous-compounding terms. Crypto intraday
    # horizons are short enough that 0 is defensible; keep it configurable.
    risk_free_rate: float = 0.0
    # Drift override. None -> use risk-neutral drift (r). A float here
    # injects a non-zero mu for sensitivity analysis only.
    drift_override: float | None = None

    # --- Edge detection --------------------------------------------------------
    # Minimum absolute mispricing (|model - market|) to enter.
    edge_threshold: float = 0.05
    # Exit when the *remaining* edge falls below this. Set to None to
    # disable early exit and hold every position to settlement.
    exit_edge_threshold: float | None = 0.01
    # Exit when the edge's sign flips (model moves against the position).
    exit_on_sign_flip: bool = True
    # Force exit when fewer than this many seconds remain. Protects from
    # last-minute spread blowouts near expiry.
    exit_min_ttm_s: int = 60
    # Upper bound on holding period in seconds after entry; None = no cap.
    max_hold_s: int | None = None
    # Kelly fraction cap. Fractional Kelly is applied on top.
    kelly_cap: float = 0.25
    kelly_fraction: float = 0.5
    # Stake sizing mode: "flat" or "kelly".
    stake_mode: str = "flat"
    flat_stake: float = 1.0

    # --- Execution assumptions (backtest only) ---------------------------------
    # Taker fee per fill (fraction of notional). Polymarket is currently 0
    # for retail; keep configurable.
    fee_bps: float = 0.0
    # Half-spread assumption (probability units) to cross the book.
    half_spread: float = 0.01
    # Minimum time-to-expiry (seconds) to consider a market. Markets with
    # <60s left are usually too thin/noisy to price meaningfully.
    min_time_to_expiry_s: int = 60
    # Maximum time-to-expiry (seconds). Above this, the BS model is noisy
    # because sigma estimation dominates.
    max_time_to_expiry_s: int = 24 * 3600

    # --- Walk-forward ----------------------------------------------------------
    # Training window length (days) and out-of-sample step (days).
    train_days: int = 30
    test_days: int = 7

    # --- Data / caching --------------------------------------------------------
    cache_dir: Path = field(default_factory=lambda: DEFAULT_CACHE_DIR)
    binance_symbol: str = "BTC/USDT"
    binance_timeframe: str = "1m"
    polymarket_base_url: str = "https://gamma-api.polymarket.com"
    polymarket_data_url: str = "https://data-api.polymarket.com"
    polymarket_clob_url: str = "https://clob.polymarket.com"
    http_timeout_s: float = 20.0
    http_max_retries: int = 4

    # --- Misc ------------------------------------------------------------------
    log_level: str = "INFO"
    seed: int = 7

    # -------------------------------------------------------------------------
    def __post_init__(self) -> None:
        self.cache_dir = Path(self.cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        if self.stake_mode not in {"flat", "kelly"}:
            raise ValueError(f"stake_mode must be flat|kelly, got {self.stake_mode!r}")
        if not 0 < self.kelly_fraction <= 1:
            raise ValueError("kelly_fraction must be in (0, 1]")
        if not 0 < self.kelly_cap <= 1:
            raise ValueError("kelly_cap must be in (0, 1]")
        if self.edge_threshold < 0:
            raise ValueError("edge_threshold must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["cache_dir"] = str(self.cache_dir)
        return d


def _coerce(value: str, target_type: type) -> Any:
    if target_type is bool:
        return value.lower() in {"1", "true", "yes", "y", "on"}
    if target_type is int:
        return int(value)
    if target_type is float:
        return float(value)
    if target_type is Path:
        return Path(value)
    if target_type in (tuple, list):
        return tuple(v.strip() for v in value.split(",") if v.strip())
    return value


def load_config(path: str | os.PathLike[str] | None = None, **overrides: Any) -> Config:
    """Build a Config from (defaults | file | env | overrides)."""
    data: dict[str, Any] = {}
    if path is not None:
        p = Path(path)
        raw = p.read_text(encoding="utf-8")
        data = json.loads(raw) if p.suffix == ".json" else _parse_yaml_lite(raw)

    # Env overrides: BSEDGE_<FIELDNAME_UPPER>
    field_types = {f.name: f.type for f in fields(Config)}
    for key, ftype in field_types.items():
        env_key = f"BSEDGE_{key.upper()}"
        if env_key in os.environ:
            try:
                data[key] = _coerce(os.environ[env_key], ftype)  # type: ignore[arg-type]
            except Exception:
                logger.warning("Failed to parse env var %s=%r", env_key, os.environ[env_key])

    data.update(overrides)
    cfg = Config(**data)
    logging.basicConfig(
        level=getattr(logging, cfg.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return cfg


def _parse_yaml_lite(text: str) -> dict[str, Any]:
    """Minimal YAML parser for ``key: value`` lines so PyYAML is optional."""
    out: dict[str, Any] = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        k, v = line.split(":", 1)
        v = v.strip()
        if v.startswith("[") and v.endswith("]"):
            out[k.strip()] = tuple(x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip())
        elif v.lower() in {"true", "false"}:
            out[k.strip()] = v.lower() == "true"
        else:
            try:
                out[k.strip()] = int(v)
            except ValueError:
                try:
                    out[k.strip()] = float(v)
                except ValueError:
                    out[k.strip()] = v.strip("'\"")
    return out
