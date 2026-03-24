"""自動生成戦略: atr_break_11cf9e97"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'max_atr': 0.4045, 'min_atr': 0.0344, 'type': 'atr_filter'},
                         {'period': 79, 'type': 'htf_trend'}],
    'entry_signal': {'multiplier': 2.3305, 'period': 21, 'type': 'atr_break'},
    'exit_rules': {   'atr_period': 10,
                      'sl_atr_mult': 2.0369,
                      'sl_type': 'atr_mult',
                      'tp_pips': 0.215,
                      'tp_type': 'fixed'},
    'name': 'atr_break_11cf9e97'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "atr_break_11cf9e97"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
