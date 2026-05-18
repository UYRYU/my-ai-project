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
    polygon_rpc: str
    polymarket_api_key: str
    polymarket_api_secret: str
    polymarket_api_passphrase: str
    sports_tags: tuple[str, ...]
    min_edge: float
    max_position_usd: float
    bankroll_usd: float
    poll_seconds: float
    dry_run: bool
    mock: bool
    once: bool


def load() -> Config:
    return Config(
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        polymarket_private_key=os.environ.get("POLYMARKET_PRIVATE_KEY", ""),
        polymarket_funder=os.environ.get("POLYMARKET_FUNDER_ADDRESS", ""),
        polymarket_host=os.environ.get("POLYMARKET_HOST", "https://clob.polymarket.com"),
        polygon_rpc=os.environ.get("POLYGON_RPC", "https://polygon-rpc.com"),
        polymarket_api_key=os.environ.get("POLYMARKET_API_KEY", ""),
        polymarket_api_secret=os.environ.get("POLYMARKET_API_SECRET", ""),
        polymarket_api_passphrase=os.environ.get("POLYMARKET_API_PASSPHRASE", ""),
        sports_tags=tuple(t.strip().lower() for t in os.environ.get("BOT_SPORTS_TAGS", "nba,nfl").split(",") if t.strip()),
        min_edge=float(os.environ.get("BOT_MIN_EDGE", "0.003")),
        max_position_usd=float(os.environ.get("BOT_MAX_POSITION_USD", "50")),
        bankroll_usd=float(os.environ.get("BOT_BANKROLL_USD", "500")),
        poll_seconds=float(os.environ.get("BOT_POLL_SECONDS", "2")),
        dry_run=os.environ.get("BOT_DRY_RUN", "true").lower() == "true",
        mock=os.environ.get("BOT_MOCK", "false").lower() == "true",
        once=os.environ.get("BOT_ONCE", "false").lower() == "true",
    )
