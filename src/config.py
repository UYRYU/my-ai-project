import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    anthropic_api_key: str
    polymarket_private_key: str
    polymarket_funder: str
    polymarket_host: str
    sports_tags: tuple[str, ...]
    min_edge: float
    max_position_usd: float
    poll_seconds: float
    dry_run: bool


def load() -> Config:
    return Config(
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        polymarket_private_key=os.environ.get("POLYMARKET_PRIVATE_KEY", ""),
        polymarket_funder=os.environ.get("POLYMARKET_FUNDER_ADDRESS", ""),
        polymarket_host=os.environ.get("POLYMARKET_HOST", "https://clob.polymarket.com"),
        sports_tags=tuple(t.strip().lower() for t in os.environ.get("BOT_SPORTS_TAGS", "nba,nfl").split(",") if t.strip()),
        min_edge=float(os.environ.get("BOT_MIN_EDGE", "0.01")),
        max_position_usd=float(os.environ.get("BOT_MAX_POSITION_USD", "25")),
        poll_seconds=float(os.environ.get("BOT_POLL_SECONDS", "5")),
        dry_run=os.environ.get("BOT_DRY_RUN", "true").lower() == "true",
    )
