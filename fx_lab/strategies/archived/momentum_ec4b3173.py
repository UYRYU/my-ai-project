"""自動生成戦略: momentum_ec4b3173"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'period': 33, 'type': 'htf_trend'},
                         {'end_hour': 18, 'start_hour': 10, 'type': 'time_filter'}],
    'entry_signal': {'period': 13, 'type': 'momentum'},
    'exit_rules': {   'atr_period': 12,
                      'sl_atr_mult': 0.5035,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 1.7378,
                      'tp_type': 'atr_mult'},
    'name': 'momentum_ec4b3173'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "momentum_ec4b3173"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
