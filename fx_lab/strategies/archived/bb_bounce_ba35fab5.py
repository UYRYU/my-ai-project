"""自動生成戦略: bb_bounce_ba35fab5"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'max_atr': 0.7824, 'min_atr': 0.0885, 'type': 'atr_filter'},
                         {'end_hour': 22, 'start_hour': 8, 'type': 'time_filter'}],
    'entry_signal': {'period': 21, 'std_mult': 2.1724, 'type': 'bb_bounce'},
    'exit_rules': {   'atr_period': 12,
                      'sl_pips': 0.1145,
                      'sl_type': 'fixed',
                      'tp_pips': 0.4452,
                      'tp_type': 'fixed'},
    'name': 'bb_bounce_ba35fab5'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "bb_bounce_ba35fab5"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
