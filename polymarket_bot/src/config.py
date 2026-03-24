"""Configuration loader from .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _float(key: str, default: float) -> float:
    return float(os.getenv(key, str(default)))


def _int(key: str, default: int) -> int:
    return int(os.getenv(key, str(default)))


def _bool(key: str, default: bool) -> bool:
    return os.getenv(key, str(default)).lower() in ("true", "1", "yes")


def _str(key: str, default: str = "") -> str:
    return os.getenv(key, default)


@dataclass(frozen=True)
class Config:
    # API
    gamma_api: str = ""   # Market discovery (events, markets)
    clob_api: str = ""    # Order books & trading
    ws_url: str = ""

    # Polling
    poll_interval_sec: int = 10
    ws_reconnect_delay_sec: int = 5
    ws_max_reconnect_attempts: int = 10

    # Signal thresholds
    mispricing_threshold: float = 0.02
    spread_max: float = 0.10
    liquidity_min_size: float = 50.0
    momentum_window_sec: int = 60
    momentum_max_change: float = 0.05
    confidence_threshold: float = 60.0

    # Signal weights
    weight_mispricing: float = 0.40
    weight_spread: float = 0.25
    weight_liquidity: float = 0.20
    weight_momentum: float = 0.15

    # Paper trading
    paper_trade_size: float = 10.0
    paper_take_profit: float = 0.05
    paper_stop_loss: float = 0.03
    paper_timeout_sec: int = 300
    paper_max_positions: int = 5

    # Notifications
    discord_webhook_url: str = ""
    enable_discord: bool = False

    # Logging
    log_level: str = "INFO"
    log_file: str = "logs/bot.log"


def load_config(env_path: str | Path | None = None) -> Config:
    """Load config from .env file."""
    if env_path:
        load_dotenv(env_path)
    else:
        # Try .env in polymarket_bot dir, then cwd
        bot_dir = Path(__file__).resolve().parent.parent
        env_file = bot_dir / ".env"
        if env_file.exists():
            load_dotenv(env_file)
        else:
            load_dotenv()

    return Config(
        gamma_api=_str("POLYMARKET_GAMMA_API", "https://gamma-api.polymarket.com"),
        clob_api=_str("POLYMARKET_CLOB_API", "https://clob.polymarket.com"),
        ws_url=_str("POLYMARKET_WS_URL", "wss://ws-subscriptions-clob.polymarket.com/ws/market"),
        poll_interval_sec=_int("POLL_INTERVAL_SEC", 10),
        ws_reconnect_delay_sec=_int("WS_RECONNECT_DELAY_SEC", 5),
        ws_max_reconnect_attempts=_int("WS_MAX_RECONNECT_ATTEMPTS", 10),
        mispricing_threshold=_float("MISPRICING_THRESHOLD", 0.02),
        spread_max=_float("SPREAD_MAX", 0.10),
        liquidity_min_size=_float("LIQUIDITY_MIN_SIZE", 50.0),
        momentum_window_sec=_int("MOMENTUM_WINDOW_SEC", 60),
        momentum_max_change=_float("MOMENTUM_MAX_CHANGE", 0.05),
        confidence_threshold=_float("CONFIDENCE_THRESHOLD", 60.0),
        weight_mispricing=_float("WEIGHT_MISPRICING", 0.40),
        weight_spread=_float("WEIGHT_SPREAD", 0.25),
        weight_liquidity=_float("WEIGHT_LIQUIDITY", 0.20),
        weight_momentum=_float("WEIGHT_MOMENTUM", 0.15),
        paper_trade_size=_float("PAPER_TRADE_SIZE", 10.0),
        paper_take_profit=_float("PAPER_TAKE_PROFIT", 0.05),
        paper_stop_loss=_float("PAPER_STOP_LOSS", 0.03),
        paper_timeout_sec=_int("PAPER_TIMEOUT_SEC", 300),
        paper_max_positions=_int("PAPER_MAX_POSITIONS", 5),
        discord_webhook_url=_str("DISCORD_WEBHOOK_URL", ""),
        enable_discord=_bool("ENABLE_DISCORD", False),
        log_level=_str("LOG_LEVEL", "INFO"),
        log_file=_str("LOG_FILE", "logs/bot.log"),
    )
