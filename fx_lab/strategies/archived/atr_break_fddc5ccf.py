"""自動生成戦略: atr_break_fddc5ccf"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'max_atr': 0.416, 'min_atr': 0.0157, 'type': 'atr_filter'}],
    'entry_signal': {'multiplier': 2.5207, 'period': 17, 'type': 'atr_break'},
    'exit_rules': {   'atr_period': 14,
                      'sl_pips': 0.2457,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 1.3909,
                      'tp_type': 'atr_mult'},
    'name': 'atr_break_fddc5ccf'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "atr_break_fddc5ccf"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
