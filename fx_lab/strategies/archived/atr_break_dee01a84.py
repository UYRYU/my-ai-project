"""自動生成戦略: atr_break_dee01a84"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'max_atr': 0.7421, 'min_atr': 0.0497, 'type': 'atr_filter'},
                         {'max_atr': 0.9388, 'min_atr': 0.0453, 'type': 'atr_filter'}],
    'entry_signal': {'multiplier': 1.5138, 'period': 23, 'type': 'atr_break'},
    'exit_rules': {   'atr_period': 18,
                      'be_trigger_pips': 0.1873,
                      'breakeven': 2,
                      'reverse_signal_exit': 2,
                      'sl_atr_mult': 1.9274,
                      'sl_pips': 0.6198,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 1.955,
                      'tp_type': 'atr_mult',
                      'trail_distance': 0.2623,
                      'trail_type': 'fixed',
                      'trailing': 2},
    'name': 'atr_break_dee01a84'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "atr_break_dee01a84"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
