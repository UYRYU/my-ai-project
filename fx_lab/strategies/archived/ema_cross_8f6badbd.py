"""自動生成戦略: ema_cross_8f6badbd"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'end_hour': 20, 'start_hour': 10, 'type': 'time_filter'}],
    'entry_signal': {'long_period': 43, 'short_period': 6, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 11,
                      'max_bars': 101,
                      'sl_pips': 0.3039,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 3.6388,
                      'tp_type': 'atr_mult'},
    'name': 'ema_cross_8f6badbd'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_8f6badbd"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
