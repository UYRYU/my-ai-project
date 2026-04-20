"""Pre-trade gating. Reject orders that violate risk limits."""

from dataclasses import dataclass
from .config import Config
from .positions import Book


@dataclass(frozen=True)
class RiskDecision:
    allow: bool
    reason: str = ""


def check(opp_cost_usd: float, leg_count: int, cfg: Config, book: Book) -> RiskDecision:
    if leg_count <= 0:
        return RiskDecision(False, "no legs")
    if opp_cost_usd > cfg.max_position_usd:
        return RiskDecision(False, f"cost {opp_cost_usd:.2f} > max_position {cfg.max_position_usd}")
    if book.gross_exposure_usd() + opp_cost_usd > cfg.max_position_usd * 10:
        return RiskDecision(False, "gross exposure cap hit")
    if book.fills_today > 5000:
        return RiskDecision(False, "daily fill cap hit")
    return RiskDecision(True)
