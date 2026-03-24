"""自動生成戦略: atr_break_25edf9f8"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'max_atr': 0.9849, 'min_atr': 0.0453, 'type': 'atr_filter'},
                         {'max_atr': 0.7492, 'min_atr': 0.0496, 'type': 'atr_filter'}],
    'entry_signal': {'multiplier': 1.4435, 'period': 12, 'type': 'atr_break'},
    'exit_rules': {   'atr_period': 18,
                      'be_trigger_pips': 0.1432,
                      'breakeven': 2,
                      'reverse_signal_exit': 2,
                      'sl_atr_mult': 2.204,
                      'sl_pips': 0.2154,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.1381,
                      'tp_type': 'atr_mult',
                      'trail_distance': 0.3366,
                      'trail_type': 'fixed',
                      'trailing': True},
    'name': 'atr_break_25edf9f8'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "atr_break_25edf9f8"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
