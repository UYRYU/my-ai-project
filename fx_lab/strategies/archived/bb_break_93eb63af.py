"""自動生成戦略: bb_break_93eb63af"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'end_hour': 21, 'start_hour': 10, 'type': 'time_filter'},
                         {'max_atr': 0.5111, 'min_atr': 0.0602, 'type': 'atr_filter'}],
    'entry_signal': {'period': 14, 'std_mult': 2.9699, 'type': 'bb_break'},
    'exit_rules': {   'atr_period': 7,
                      'reverse_signal_exit': True,
                      'sl_pips': 0.3,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 1.2296,
                      'tp_type': 'atr_mult'},
    'name': 'bb_break_93eb63af'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "bb_break_93eb63af"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
