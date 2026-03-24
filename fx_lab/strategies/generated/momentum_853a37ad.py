"""自動生成戦略: momentum_853a37ad"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'end_hour': 21, 'start_hour': 6, 'type': 'time_filter'},
                         {'max_atr': 0.4229, 'min_atr': 0.0565, 'type': 'atr_filter'}],
    'entry_signal': {'period': 12, 'type': 'momentum'},
    'exit_rules': {   'atr_period': 14,
                      'sl_atr_mult': 2.3255,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 3.6153,
                      'tp_type': 'atr_mult'},
    'name': 'momentum_853a37ad'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "momentum_853a37ad"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
