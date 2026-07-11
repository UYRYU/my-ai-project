"""自動生成戦略: atr_break_0d7dd50e"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'max_atr': 0.7195, 'min_atr': 0.0361, 'type': 'atr_filter'}],
    'entry_signal': {'multiplier': 1.5282, 'period': 21, 'type': 'atr_break'},
    'exit_rules': {   'atr_period': 13,
                      'be_trigger_pips': 0.1653,
                      'breakeven': 2,
                      'reverse_signal_exit': 2,
                      'sl_atr_mult': 2.2963,
                      'sl_pips': 0.3315,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.6663,
                      'tp_type': 'atr_mult',
                      'trail_distance': 0.3366,
                      'trail_type': 'fixed',
                      'trailing': 1},
    'name': 'atr_break_0d7dd50e'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "atr_break_0d7dd50e"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
