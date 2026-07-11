"""自動生成戦略: atr_break_0ae7fef9"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'multiplier': 2.4618, 'period': 18, 'type': 'atr_break'},
    'exit_rules': {   'atr_period': 7,
                      'sl_atr_mult': 1.6457,
                      'sl_type': 'atr_mult',
                      'tp_pips': 0.1269,
                      'tp_type': 'fixed',
                      'trail_atr_mult': 1.4306,
                      'trail_type': 'atr_mult',
                      'trailing': True},
    'name': 'atr_break_0ae7fef9'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "atr_break_0ae7fef9"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
