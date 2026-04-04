"""設定管理モジュール。.envファイルから設定を読み込む。"""

import csv
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


@dataclass
class WalletEntry:
    address: str
    label: str
    note: str = ""


@dataclass
class Config:
    discord_webhook_url: str = ""
    poll_interval_sec: int = 60
    signal_time_window_sec: int = 300
    signal_min_wallets: int = 3
    signal_strong_amount_threshold: float = 1000.0
    data_source: str = "mock"
    db_path: str = "tracker.db"
    log_level: str = "INFO"
    wallets: list[WalletEntry] = field(default_factory=list)

    # --- Execution 設定 ---
    trading_mode: str = "paper"  # "paper", "live", "dry-run"
    max_order_usd: float = 50.0
    max_position_usd: float = 200.0
    max_daily_loss_usd: float = 100.0
    min_signal_level: str = "STRONG"
    allow_live_trading: bool = False
    kill_switch: bool = False
    order_cooldown_sec: int = 300
    legacy_paper_model: bool = False

    # --- Polymarket認証情報 ---
    poly_private_key: str = ""
    poly_api_key: str = ""
    poly_api_secret: str = ""
    poly_api_passphrase: str = ""

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            discord_webhook_url=os.getenv("DISCORD_WEBHOOK_URL", ""),
            poll_interval_sec=int(os.getenv("POLL_INTERVAL_SEC", "60")),
            signal_time_window_sec=int(os.getenv("SIGNAL_TIME_WINDOW_SEC", "300")),
            signal_min_wallets=int(os.getenv("SIGNAL_MIN_WALLETS", "3")),
            signal_strong_amount_threshold=float(
                os.getenv("SIGNAL_STRONG_AMOUNT_THRESHOLD", "1000")
            ),
            data_source=os.getenv("DATA_SOURCE", "mock"),
            db_path=os.getenv("DB_PATH", "tracker.db"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            # Execution
            trading_mode=os.getenv("TRADING_MODE", "paper"),
            max_order_usd=float(os.getenv("MAX_ORDER_USD", "50")),
            max_position_usd=float(os.getenv("MAX_POSITION_USD", "200")),
            max_daily_loss_usd=float(os.getenv("MAX_DAILY_LOSS_USD", "100")),
            min_signal_level=os.getenv("MIN_SIGNAL_LEVEL", "STRONG"),
            allow_live_trading=os.getenv("ALLOW_LIVE_TRADING", "false").lower() == "true",
            kill_switch=os.getenv("KILL_SWITCH", "false").lower() == "true",
            order_cooldown_sec=int(os.getenv("ORDER_COOLDOWN_SEC", "300")),
            legacy_paper_model=os.getenv("LEGACY_PAPER_MODEL", "false").lower() == "true",
            # Polymarket Auth
            poly_private_key=os.getenv("POLY_PRIVATE_KEY", ""),
            poly_api_key=os.getenv("POLY_API_KEY", ""),
            poly_api_secret=os.getenv("POLY_API_SECRET", ""),
            poly_api_passphrase=os.getenv("POLY_API_PASSPHRASE", ""),
        )

    def load_wallets(self, csv_path: str = "wallets_seed.csv") -> None:
        path = Path(csv_path)
        if not path.exists():
            logger.warning("ウォレットCSVが見つかりません: %s", csv_path)
            return
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                self.wallets.append(
                    WalletEntry(
                        address=row["address"].strip().lower(),
                        label=row.get("label", "").strip(),
                        note=row.get("note", "").strip(),
                    )
                )
        logger.info("ウォレット %d 件を読み込みました", len(self.wallets))

    def setup_logging(self) -> None:
        import sys

        # Windows cmd.exe での文字化け対策
        if sys.platform == "win32" and sys.stdout.encoding != "utf-8":
            import io
            sys.stdout = io.TextIOWrapper(
                sys.stdout.buffer, encoding="utf-8", errors="replace"
            )
            sys.stderr = io.TextIOWrapper(
                sys.stderr.buffer, encoding="utf-8", errors="replace"
            )

        logging.basicConfig(
            level=getattr(logging, self.log_level.upper(), logging.INFO),
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
