"""自動生成戦略: momentum_2a70dfde"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'end_hour': 19, 'start_hour': 9, 'type': 'time_filter'},
                         {'max_atr': 0.4637, 'min_atr': 0.0669, 'type': 'atr_filter'}],
    'entry_signal': {'period': 13, 'type': 'momentum'},
    'exit_rules': {   'atr_period': 14,
                      'sl_atr_mult': 2.3255,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 2.6666,
                      'tp_type': 'atr_mult'},
    'name': 'momentum_2a70dfde'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "momentum_2a70dfde"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
