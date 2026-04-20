"""Live edge scanner. Read-only: emits alerts; does NOT place trades.

The scanner loops over currently-active Up/Down markets, pulls the latest
CLOB mid price, fetches recent BTC bars, estimates sigma, and prints a
table of mispricings exceeding the configured threshold. Output is plain
log lines suitable for piping into notifications or a dashboard.

This module intentionally exposes no ``buy`` / ``sell`` / ``sign``
primitives. If you want to act on alerts, do it in a separate process.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import pandas as pd

from .binance_client import BinanceClient
from .config import Config
from .market_loader import UpDownMarket, filter_active
from .polymarket_client import PolymarketClient
from .pricing import quote_edge
from .volatility import estimate_sigma

logger = logging.getLogger(__name__)


@dataclass
class Alert:
    ts: int
    slug: str
    side: str
    model_price: float
    market_price: float
    edge: float
    sigma: float
    time_to_expiry_s: int
    spot: float
    strike: float

    def format(self) -> str:
        return (
            f"{datetime.fromtimestamp(self.ts, tz=timezone.utc).isoformat()} "
            f"{self.slug} side={self.side} "
            f"model={self.model_price:.3f} market={self.market_price:.3f} "
            f"edge={self.edge:+.3f} sigma={self.sigma:.3f} "
            f"ttm={self.time_to_expiry_s}s spot={self.spot:.2f} K={self.strike:.2f}"
        )


def scan_once(
    markets: Iterable[UpDownMarket],
    poly: PolymarketClient,
    binance: BinanceClient,
    cfg: Config,
    *,
    sigma_window_min: int,
    sigma_estimator: str,
    now_ts: int | None = None,
) -> list[Alert]:
    """Produce edge alerts for the given markets at the current time."""
    now_ts = now_ts if now_ts is not None else int(time.time())
    active = filter_active(markets, now_ts)
    if not active:
        logger.info("no active markets at %s", now_ts)
        return []

    end_ms = now_ts * 1000
    start_ms = end_ms - (sigma_window_min + 5) * 60_000
    bars = binance.fetch_ohlcv(start_ms, end_ms, use_cache=True)
    if bars.empty or len(bars) < sigma_window_min + 2:
        logger.warning("insufficient BTC bars for scan (%d rows)", len(bars))
        return []
    spot = float(bars["close"].iloc[-1])
    sigma = estimate_sigma(
        bars,
        window_min=sigma_window_min,
        estimator=sigma_estimator,
        minutes_per_year=cfg.minutes_per_year,
        sigma_floor=cfg.sigma_floor_annual,
    )

    alerts: list[Alert] = []
    for mkt in active:
        if mkt.reference_price is None or mkt.up_token_id is None:
            continue
        ttm_s = mkt.close_ts - now_ts
        if ttm_s < cfg.min_time_to_expiry_s or ttm_s > cfg.max_time_to_expiry_s:
            continue
        ttm_years = ttm_s / (cfg.minutes_per_year * 60)
        try:
            mid_up = poly.clob_mid(mkt.up_token_id)
        except Exception as exc:
            logger.warning("clob_mid failed for %s: %s", mkt.slug, exc)
            continue
        if mid_up is None:
            continue
        for side, market_p in (("UP", mid_up), ("DOWN", 1.0 - mid_up)):
            q = quote_edge(
                side,
                spot=spot,
                strike=mkt.reference_price,
                time_to_expiry=ttm_years,
                sigma=sigma,
                market_price=market_p,
                rate=cfg.risk_free_rate,
                drift=cfg.drift_override,
            )
            if q.edge > cfg.edge_threshold:
                alerts.append(
                    Alert(
                        ts=now_ts,
                        slug=mkt.slug,
                        side=side,
                        model_price=q.model_price,
                        market_price=q.market_price,
                        edge=q.edge,
                        sigma=sigma,
                        time_to_expiry_s=ttm_s,
                        spot=spot,
                        strike=float(mkt.reference_price),
                    )
                )
    for a in alerts:
        logger.info("ALERT %s", a.format())
    return alerts
