"""自動生成戦略: atr_break_909b7334"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'max_atr': 0.7421, 'min_atr': 0.0391, 'type': 'atr_filter'},
                         {'max_atr': 0.9388, 'min_atr': 0.037, 'type': 'atr_filter'}],
    'entry_signal': {'multiplier': 1.705, 'period': 23, 'type': 'atr_break'},
    'exit_rules': {   'atr_period': 18,
                      'be_trigger_pips': 0.1873,
                      'breakeven': 4,
                      'reverse_signal_exit': 1,
                      'sl_atr_mult': 2.204,
                      'sl_pips': 0.4673,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.804,
                      'tp_type': 'atr_mult',
                      'trail_distance': 0.3062,
                      'trail_type': 'fixed',
                      'trailing': True},
    'name': 'atr_break_909b7334'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "atr_break_909b7334"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
