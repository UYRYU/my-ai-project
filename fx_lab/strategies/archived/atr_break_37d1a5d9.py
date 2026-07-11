"""自動生成戦略: atr_break_37d1a5d9"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'max_atr': 0.9388, 'min_atr': 0.0461, 'type': 'atr_filter'},
                         {'max_atr': 0.7421, 'min_atr': 0.0497, 'type': 'atr_filter'},
                         {'end_hour': 20, 'start_hour': 7, 'type': 'time_filter'}],
    'entry_signal': {'multiplier': 1.4419, 'period': 12, 'type': 'atr_break'},
    'exit_rules': {   'atr_period': 18,
                      'be_trigger_pips': 0.1581,
                      'breakeven': 2,
                      'reverse_signal_exit': 2,
                      'sl_atr_mult': 2.357,
                      'sl_pips': 0.228,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.2823,
                      'tp_type': 'atr_mult',
                      'trail_distance': 0.2623,
                      'trail_type': 'fixed',
                      'trailing': 2},
    'name': 'atr_break_37d1a5d9'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "atr_break_37d1a5d9"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
