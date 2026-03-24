"""自動生成戦略: ema_cross_13cabf4a"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'max_atr': 0.7182, 'min_atr': 0.0103, 'type': 'atr_filter'},
                         {'end_hour': 22, 'start_hour': 10, 'type': 'time_filter'}],
    'entry_signal': {'long_period': 20, 'short_period': 4, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 21,
                      'reverse_signal_exit': True,
                      'sl_pips': 0.3771,
                      'sl_type': 'fixed',
                      'tp_pips': 0.4582,
                      'tp_type': 'fixed',
                      'trail_atr_mult': 1.6069,
                      'trail_type': 'atr_mult',
                      'trailing': True},
    'name': 'ema_cross_13cabf4a'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_13cabf4a"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
