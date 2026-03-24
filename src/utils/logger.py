"""Logging utility: writes to both console (stdout) and a daily log file."""
import logging
import sys
from pathlib import Path
from datetime import datetime


def setup_logger(
    name: str,
    log_dir: str = "data/logs",
    level: int = logging.INFO,
) -> logging.Logger:
    """Return a configured logger that writes to console and to a daily log file.

    Args:
        name: Logger name (typically ``__name__``).
        log_dir: Directory for log files, relative to the working directory.
        level: Log level (default: INFO).

    Returns:
        Configured :class:`logging.Logger` instance.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        # Avoid duplicate handlers when the same logger is requested multiple times
        return logger

    logger.setLevel(level)

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d")
    log_file = log_path / f"{timestamp}.log"

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # File handler
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger
