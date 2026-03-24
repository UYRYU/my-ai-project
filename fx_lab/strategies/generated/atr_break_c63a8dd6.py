"""自動生成戦略: atr_break_c63a8dd6"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'multiplier': 1.5138, 'period': 23, 'type': 'atr_break'},
    'exit_rules': {   'atr_period': 15,
                      'be_trigger_pips': 0.1873,
                      'breakeven': 2,
                      'reverse_signal_exit': 2,
                      'sl_atr_mult': 2.17,
                      'sl_pips': 0.5057,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.7412,
                      'tp_pips': 1.1209,
                      'tp_type': 'atr_mult',
                      'trail_distance': 0.2745,
                      'trail_type': 'fixed',
                      'trailing': 1},
    'name': 'atr_break_c63a8dd6'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "atr_break_c63a8dd6"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
