"""Pre-trade gating with daily circuit breakers."""

from dataclasses import dataclass, field
from datetime import date
from .config import Config
from .positions import Book


@dataclass(frozen=True)
class RiskDecision:
    allow: bool
    reason: str = ""


@dataclass
class DailyCounters:
    trading_day: date = field(default_factory=date.today)
    baskets_today: int = 0
    realized_pnl_today: float = 0.0

    def roll_if_new_day(self) -> None:
        today = date.today()
        if today != self.trading_day:
            self.trading_day = today
            self.baskets_today = 0
            self.realized_pnl_today = 0.0


def check(
    opp_cost_usd: float,
    leg_count: int,
    cfg: Config,
    book: Book,
    counters: DailyCounters,
    *,
    max_daily_loss_usd: float = 100.0,
    max_baskets_per_day: int = 200,
    max_concurrent_baskets: int = 20,
    gross_exposure_cap_multiplier: float = 10.0,
) -> RiskDecision:
    counters.roll_if_new_day()

    if leg_count <= 0:
        return RiskDecision(False, "no legs")
    if opp_cost_usd <= 0:
        return RiskDecision(False, "non-positive cost")
    if opp_cost_usd > cfg.max_position_usd:
        return RiskDecision(False, f"cost {opp_cost_usd:.2f} > max_position {cfg.max_position_usd}")

    cap = cfg.max_position_usd * gross_exposure_cap_multiplier
    if book.gross_exposure_usd() + opp_cost_usd > cap:
        return RiskDecision(False, f"gross exposure cap {cap:.0f} hit")

    if counters.baskets_today >= max_baskets_per_day:
        return RiskDecision(False, f"daily basket cap {max_baskets_per_day} hit")

    if len(book.positions) >= max_concurrent_baskets * leg_count:
        return RiskDecision(False, f"concurrent basket cap hit")

    if counters.realized_pnl_today <= -abs(max_daily_loss_usd):
        return RiskDecision(False, f"daily loss cap ${max_daily_loss_usd} hit")

    return RiskDecision(True)
