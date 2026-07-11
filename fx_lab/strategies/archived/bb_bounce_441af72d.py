"""自動生成戦略: bb_bounce_441af72d"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'end_hour': 18, 'start_hour': 10, 'type': 'time_filter'},
                         {'max_atr': 0.8669, 'min_atr': 0.0937, 'type': 'atr_filter'}],
    'entry_signal': {'period': 18, 'std_mult': 2.1056, 'type': 'bb_bounce'},
    'exit_rules': {   'atr_period': 17,
                      'sl_pips': 0.4017,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 3.1695,
                      'tp_type': 'atr_mult',
                      'trail_atr_mult': 1.2971,
                      'trail_distance': 0.1039,
                      'trail_type': 'atr_mult',
                      'trailing': True},
    'name': 'bb_bounce_441af72d'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "bb_bounce_441af72d"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
