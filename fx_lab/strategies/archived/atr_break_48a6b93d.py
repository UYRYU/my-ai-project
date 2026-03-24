"""自動生成戦略: atr_break_48a6b93d"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'multiplier': 1.5076, 'period': 21, 'type': 'atr_break'},
    'exit_rules': {   'atr_period': 13,
                      'be_trigger_pips': 0.3839,
                      'breakeven': True,
                      'sl_pips': 0.3231,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.0792,
                      'tp_type': 'atr_mult',
                      'trail_distance': 0.3366,
                      'trail_type': 'fixed',
                      'trailing': 1},
    'name': 'atr_break_48a6b93d'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "atr_break_48a6b93d"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
