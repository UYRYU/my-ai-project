"""自動生成戦略: bb_bounce_83e1fc34"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'max_atr': 0.5948, 'min_atr': 0.074, 'type': 'atr_filter'},
                         {'end_hour': 21, 'start_hour': 9, 'type': 'time_filter'}],
    'entry_signal': {'period': 19, 'std_mult': 2.3485, 'type': 'bb_bounce'},
    'exit_rules': {   'atr_period': 12,
                      'sl_pips': 0.2896,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.3587,
                      'tp_type': 'atr_mult'},
    'name': 'bb_bounce_83e1fc34'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "bb_bounce_83e1fc34"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
