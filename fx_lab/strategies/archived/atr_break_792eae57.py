"""自動生成戦略: atr_break_792eae57"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'end_hour': 19, 'start_hour': 9, 'type': 'time_filter'},
                         {'period': 53, 'type': 'htf_trend'}],
    'entry_signal': {'multiplier': 2.5421, 'period': 17, 'type': 'atr_break'},
    'exit_rules': {   'atr_period': 18,
                      'reverse_signal_exit': True,
                      'sl_pips': 0.4632,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 1.6494,
                      'tp_type': 'atr_mult'},
    'name': 'atr_break_792eae57'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "atr_break_792eae57"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
