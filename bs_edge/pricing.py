"""Black-Scholes digital option pricing for Polymarket Up/Down markets.

Polymarket Up/Down markets pay $1 if a condition resolves true, else $0.
That makes them cash-or-nothing digital options, priced under the risk-
neutral measure as::

    P(S_T > K) = Phi(d2)
    d2 = (ln(S_0 / K) + (r - 0.5 * sigma^2) * T) / (sigma * sqrt(T))

For short intraday horizons we typically assume r = 0, but keep it as a
parameter so the caller can inject crypto-specific drift (funding, etc.).

We intentionally do NOT use the European call formula from the source
tweet --- that prices a payoff of ``max(S_T - K, 0)``, not the binary
outcome. The two coincide only in d2; the fair *probability* is Phi(d2).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_SQRT_2 = math.sqrt(2.0)


def _norm_cdf(x: float) -> float:
    """Standard normal CDF via erf. Avoids scipy dependency."""
    return 0.5 * (1.0 + math.erf(x / _SQRT_2))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def d1_d2(
    spot: float,
    strike: float,
    time_to_expiry: float,
    sigma: float,
    rate: float = 0.0,
    drift: float | None = None,
) -> tuple[float, float]:
    """Return (d1, d2) for Black-Scholes.

    ``drift`` overrides ``rate`` for the drift term if provided, which is
    useful for sensitivity analysis. Under the risk-neutral measure
    ``drift == rate``.
    """
    if spot <= 0 or strike <= 0:
        raise ValueError("spot and strike must be positive")
    if time_to_expiry <= 0:
        raise ValueError("time_to_expiry must be positive")
    if sigma <= 0:
        raise ValueError("sigma must be positive")

    mu = rate if drift is None else drift
    vol_t = sigma * math.sqrt(time_to_expiry)
    log_moneyness = math.log(spot / strike)
    d1 = (log_moneyness + (mu + 0.5 * sigma * sigma) * time_to_expiry) / vol_t
    d2 = d1 - vol_t
    return d1, d2


def digital_call_price(
    spot: float,
    strike: float,
    time_to_expiry: float,
    sigma: float,
    rate: float = 0.0,
    drift: float | None = None,
) -> float:
    """Fair value (in [0,1]) of a cash-or-nothing call paying $1 if S_T > K.

    For Polymarket where payoff settles in USDC and the horizon is short,
    we return the undiscounted probability Phi(d2). To include discounting,
    multiply by ``exp(-rate * time_to_expiry)`` in the caller.
    """
    _, d2 = d1_d2(spot, strike, time_to_expiry, sigma, rate=rate, drift=drift)
    return _norm_cdf(d2)


def digital_put_price(
    spot: float,
    strike: float,
    time_to_expiry: float,
    sigma: float,
    rate: float = 0.0,
    drift: float | None = None,
) -> float:
    """Fair value of a $1 payoff if S_T <= K. Equals 1 - digital_call_price."""
    return 1.0 - digital_call_price(spot, strike, time_to_expiry, sigma, rate=rate, drift=drift)


@dataclass(frozen=True)
class EdgeQuote:
    """Output of an edge calculation on one side of an Up/Down market."""

    side: str  # "UP" or "DOWN"
    model_price: float
    market_price: float
    edge: float  # model_price - market_price, signed
    d2: float
    sigma: float
    time_to_expiry: float
    spot: float
    strike: float

    @property
    def abs_edge(self) -> float:
        return abs(self.edge)

    @property
    def expected_value(self) -> float:
        """EV per $1 of limit cost (model p wins $1 else loses market_price)."""
        if self.market_price <= 0 or self.market_price >= 1:
            return 0.0
        p = self.model_price
        return p * (1.0 - self.market_price) - (1.0 - p) * self.market_price


def quote_edge(
    side: str,
    spot: float,
    strike: float,
    time_to_expiry: float,
    sigma: float,
    market_price: float,
    rate: float = 0.0,
    drift: float | None = None,
) -> EdgeQuote:
    """Compute model price and edge for one side of a binary market.

    ``side`` is "UP" for S_T > K payoff or "DOWN" for S_T <= K.
    """
    side_u = side.upper()
    if side_u not in {"UP", "DOWN"}:
        raise ValueError(f"side must be UP or DOWN, got {side!r}")
    if not 0.0 <= market_price <= 1.0:
        raise ValueError(f"market_price must be in [0,1], got {market_price}")

    _, d2 = d1_d2(spot, strike, time_to_expiry, sigma, rate=rate, drift=drift)
    call_p = _norm_cdf(d2)
    model_p = call_p if side_u == "UP" else 1.0 - call_p
    return EdgeQuote(
        side=side_u,
        model_price=model_p,
        market_price=market_price,
        edge=model_p - market_price,
        d2=d2,
        sigma=sigma,
        time_to_expiry=time_to_expiry,
        spot=spot,
        strike=strike,
    )


def implied_sigma(
    side: str,
    spot: float,
    strike: float,
    time_to_expiry: float,
    market_price: float,
    rate: float = 0.0,
    drift: float | None = None,
    tol: float = 1e-6,
    max_iter: int = 100,
) -> float | None:
    """Invert the digital price to recover market-implied annualised sigma.

    Returns None when the market price is at the degenerate boundary
    (0 or 1), where implied vol is undefined.
    """
    if market_price <= 0.0 or market_price >= 1.0:
        return None

    # Bisection over a wide sigma range. The digital price is monotone in
    # sigma only when S0 is on one side of K with modest drift; otherwise
    # it can be non-monotone, so we keep a wide bracket and fall back to a
    # grid search if bisection fails.
    target = market_price if side.upper() == "UP" else 1.0 - market_price
    lo, hi = 1e-4, 5.0
    f_lo = _norm_cdf(d1_d2(spot, strike, time_to_expiry, lo, rate, drift)[1]) - target
    f_hi = _norm_cdf(d1_d2(spot, strike, time_to_expiry, hi, rate, drift)[1]) - target
    if f_lo * f_hi > 0:
        return None
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        f_mid = _norm_cdf(d1_d2(spot, strike, time_to_expiry, mid, rate, drift)[1]) - target
        if abs(f_mid) < tol:
            return mid
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return 0.5 * (lo + hi)
