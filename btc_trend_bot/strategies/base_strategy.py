from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd

@dataclass
class Signal:
    """Trading signal."""
    timestamp: pd.Timestamp
    direction: str  # "long" only for this bot
    entry_price: float
    stop_loss: float
    take_profit: Optional[float] = None
    size_pct: float = 100.0
    strategy_name: str = ""
    metadata: dict = field(default_factory=dict)

class BaseStrategy(ABC):
    """Base class for all trading strategies."""

    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        """Generate entry signals from prepared OHLCV+indicators data.
        df already has all indicators added by FeatureEngineer.
        Only generate signals where trend regime is 'bull' (or composite uptrend is True).
        """
        pass

    def get_param_space(self) -> dict:
        """Return parameter ranges for optimization. Override in subclasses."""
        return {}
