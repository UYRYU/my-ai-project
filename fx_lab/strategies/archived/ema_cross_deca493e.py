"""自動生成戦略: ema_cross_deca493e"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'end_hour': 20, 'start_hour': 9, 'type': 'time_filter'},
                         {'max_atr': 0.6704, 'min_atr': 0.0396, 'type': 'atr_filter'}],
    'entry_signal': {'long_period': 35, 'short_period': 3, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 21,
                      'sl_atr_mult': 1.3555,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 3.7755,
                      'tp_type': 'atr_mult'},
    'name': 'ema_cross_deca493e'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_deca493e"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
