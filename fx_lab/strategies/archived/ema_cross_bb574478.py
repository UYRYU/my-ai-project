"""自動生成戦略: ema_cross_bb574478"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'end_hour': 22, 'start_hour': 7, 'type': 'time_filter'},
                         {'max_atr': 0.3107, 'min_atr': 0.0193, 'type': 'atr_filter'}],
    'entry_signal': {'long_period': 73, 'short_period': 9, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 15,
                      'be_trigger_pips': 0.2334,
                      'breakeven': 2,
                      'sl_atr_mult': 3.7592,
                      'sl_type': 'atr_mult',
                      'tp_pips': 1.1209,
                      'tp_type': 'fixed'},
    'name': 'ema_cross_bb574478'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_bb574478"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
