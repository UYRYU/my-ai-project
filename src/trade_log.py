"""Append-only JSONL log so you can replay/audit decisions."""

import json
import time
from pathlib import Path
from typing import Any

LOG_PATH = Path("trades.jsonl")


def write(event: str, **payload: Any) -> None:
    record = {"ts": time.time(), "event": event, **payload}
    with LOG_PATH.open("a") as f:
        f.write(json.dumps(record, sort_keys=True, default=str) + "\n")
