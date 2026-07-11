"""自動生成戦略: atr_break_e0154dc2"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'multiplier': 1.2523, 'period': 10, 'type': 'atr_break'},
    'exit_rules': {   'atr_period': 21,
                      'sl_atr_mult': 1.4132,
                      'sl_type': 'atr_mult',
                      'tp_pips': 0.7108,
                      'tp_type': 'fixed'},
    'name': 'atr_break_e0154dc2'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "atr_break_e0154dc2"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
