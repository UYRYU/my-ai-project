"""自動生成戦略: ema_cross_db6937e7"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'long_period': 20, 'short_period': 9, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 20,
                      'max_bars': 244,
                      'sl_pips': 0.4556,
                      'sl_type': 'fixed',
                      'tp_pips': 0.5147,
                      'tp_type': 'fixed'},
    'name': 'ema_cross_db6937e7'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_db6937e7"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
