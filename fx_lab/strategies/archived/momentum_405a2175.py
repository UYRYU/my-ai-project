"""自動生成戦略: momentum_405a2175"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'end_hour': 20, 'start_hour': 10, 'type': 'time_filter'}],
    'entry_signal': {'period': 19, 'type': 'momentum'},
    'exit_rules': {   'atr_period': 12,
                      'max_bars': 242,
                      'sl_atr_mult': 1.4084,
                      'sl_type': 'atr_mult',
                      'tp_pips': 0.5551,
                      'tp_type': 'fixed'},
    'name': 'momentum_405a2175'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "momentum_405a2175"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
