"""自動生成戦略: ema_cross_b512408c"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'period': 84, 'type': 'htf_trend'},
                         {'end_hour': 20, 'start_hour': 9, 'type': 'time_filter'}],
    'entry_signal': {'long_period': 33, 'short_period': 3, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 21,
                      'sl_atr_mult': 1.3208,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 3.4546,
                      'tp_pips': 0.4514,
                      'tp_type': 'atr_mult'},
    'name': 'ema_cross_b512408c'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_b512408c"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
