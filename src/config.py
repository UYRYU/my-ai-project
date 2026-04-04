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
        logging.basicConfig(
            level=getattr(logging, self.log_level.upper(), logging.INFO),
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
