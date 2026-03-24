"""自動生成戦略: momentum_12bcd399"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'max_atr': 0.6823, 'min_atr': 0.052, 'type': 'atr_filter'},
                         {'end_hour': 18, 'start_hour': 8, 'type': 'time_filter'}],
    'entry_signal': {'period': 17, 'type': 'momentum'},
    'exit_rules': {   'atr_period': 21,
                      'sl_pips': 0.4493,
                      'sl_type': 'fixed',
                      'tp_pips': 0.1788,
                      'tp_type': 'fixed'},
    'name': 'momentum_12bcd399'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "momentum_12bcd399"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
