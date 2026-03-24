"""自動生成戦略: atr_break_1d9ab100"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'multiplier': 1.9093, 'period': 21, 'type': 'atr_break'},
    'exit_rules': {   'atr_period': 13,
                      'be_trigger_pips': 0.3626,
                      'breakeven': True,
                      'sl_pips': 0.2215,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.1381,
                      'tp_type': 'atr_mult',
                      'trail_distance': 0.3692,
                      'trail_type': 'fixed',
                      'trailing': True},
    'name': 'atr_break_1d9ab100'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "atr_break_1d9ab100"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
