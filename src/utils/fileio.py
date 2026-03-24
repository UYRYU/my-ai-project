"""File I/O helpers: YAML, JSON, plain text, and directory management."""
import json
from pathlib import Path
from typing import Any

import yaml


def read_yaml(path: str | Path) -> dict[str, Any]:
    """Read a YAML file and return its contents as a dict."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def write_yaml(path: str | Path, data: dict[str, Any]) -> None:
    """Write a dict to a YAML file, creating parent directories as needed."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)


def read_json(path: str | Path) -> Any:
    """Read a JSON file.  Returns an empty list ``[]`` if the file is missing."""
    p = Path(path)
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def write_json(path: str | Path, data: Any, indent: int = 2) -> None:
    """Write data to a JSON file, creating parent directories as needed."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)


def read_text(path: str | Path) -> str:
    """Read a plain-text (or Markdown) file and return its contents."""
    with open(path, encoding="utf-8") as f:
        return f.read()


def write_text(path: str | Path, text: str) -> None:
    """Write a string to a text file, creating parent directories as needed."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def ensure_dir(path: str | Path) -> Path:
    """Ensure a directory exists (create it if needed) and return its Path."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p
