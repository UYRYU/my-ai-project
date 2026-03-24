"""自動生成戦略: atr_break_1012e23e"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'max_atr': 0.7576, 'min_atr': 0.0856, 'type': 'atr_filter'},
                         {'end_hour': 18, 'start_hour': 8, 'type': 'time_filter'}],
    'entry_signal': {'multiplier': 2.0605, 'period': 11, 'type': 'atr_break'},
    'exit_rules': {   'atr_period': 12,
                      'sl_atr_mult': 1.223,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 1.4206,
                      'tp_type': 'atr_mult'},
    'name': 'atr_break_1012e23e'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "atr_break_1012e23e"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
