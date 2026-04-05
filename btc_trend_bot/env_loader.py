"""Load .env file from project root into os.environ."""

import os
from pathlib import Path


def load_env():
    """Load .env file from project root if it exists."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    try:
        text = env_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        text = env_path.read_text(encoding="latin-1")
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())
