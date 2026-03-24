"""自動生成戦略: ema_cross_5809e979"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'long_period': 37, 'short_period': 3, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 21,
                      'sl_atr_mult': 1.2864,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 3.3569,
                      'tp_type': 'atr_mult'},
    'name': 'ema_cross_5809e979'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_5809e979"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
