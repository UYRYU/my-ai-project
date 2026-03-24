"""自動生成戦略: bb_bounce_10cf0c5d"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'end_hour': 19, 'start_hour': 7, 'type': 'time_filter'}],
    'entry_signal': {'period': 15, 'std_mult': 2.7137, 'type': 'bb_bounce'},
    'exit_rules': {   'atr_period': 17,
                      'max_bars': 148,
                      'sl_atr_mult': 2.3419,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 1.415,
                      'tp_type': 'atr_mult'},
    'name': 'bb_bounce_10cf0c5d'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "bb_bounce_10cf0c5d"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
