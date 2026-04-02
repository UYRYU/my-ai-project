"""Simple JSON-based state persistence for paper trading."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger


class StateStore:
    """Persist paper trading state to a JSON file.

    Stores capital, trades, equity history, and arbitrary key-value pairs
    so that a paper-trading session can be resumed after restart.
    """

    def __init__(self, filepath: str = "data/paper_state.json") -> None:
        self.filepath = Path(filepath)
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        self._state: dict = self._load()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load(self) -> dict:
        """Load state from disk. Returns empty state if file missing or corrupt."""
        if not self.filepath.exists():
            logger.info("No existing state file found at {}, starting fresh", self.filepath)
            return self._empty_state()

        try:
            with open(self.filepath, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            logger.info("Loaded paper trading state from {} ({} trades)", self.filepath, len(data.get("trades", [])))
            return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load state from {}: {}. Starting fresh.", self.filepath, exc)
            return self._empty_state()

    @staticmethod
    def _empty_state() -> dict:
        """Return a blank state structure."""
        return {
            "trades": [],
            "equity_history": [],
            "meta": {},
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Persist current state to disk."""
        try:
            tmp_path = self.filepath.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(self._state, fh, indent=2, default=str)
            tmp_path.replace(self.filepath)
            logger.debug("State saved to {}", self.filepath)
        except OSError as exc:
            logger.error("Failed to save state to {}: {}", self.filepath, exc)

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a value from the meta section."""
        return self._state.get("meta", {}).get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Store a value in the meta section."""
        if "meta" not in self._state:
            self._state["meta"] = {}
        self._state["meta"][key] = value

    def get_trades(self) -> list[dict]:
        """Return all recorded trades."""
        return self._state.get("trades", [])

    def add_trade(self, trade: dict) -> None:
        """Append a completed trade record and persist."""
        if "trades" not in self._state:
            self._state["trades"] = []
        self._state["trades"].append(trade)
        self.save()
        logger.debug("Trade recorded (total: {})", len(self._state["trades"]))

    def get_equity_history(self) -> list[dict]:
        """Return the equity snapshot history."""
        return self._state.get("equity_history", [])

    def add_equity_snapshot(self, timestamp: str, equity: float) -> None:
        """Append an equity snapshot (timestamp + equity value)."""
        if "equity_history" not in self._state:
            self._state["equity_history"] = []
        self._state["equity_history"].append({
            "timestamp": timestamp,
            "equity": equity,
        })

    def reset(self) -> None:
        """Wipe all state and remove the persisted file."""
        self._state = self._empty_state()
        try:
            if self.filepath.exists():
                self.filepath.unlink()
            logger.info("State reset and file removed: {}", self.filepath)
        except OSError as exc:
            logger.warning("Could not remove state file: {}", exc)
