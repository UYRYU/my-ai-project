"""自動生成戦略: momentum_560382f8"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'end_hour': 21, 'start_hour': 11, 'type': 'time_filter'}],
    'entry_signal': {'period': 21, 'type': 'momentum'},
    'exit_rules': {   'atr_period': 12,
                      'max_bars': 242,
                      'sl_atr_mult': 1.3533,
                      'sl_type': 'atr_mult',
                      'tp_pips': 0.6197,
                      'tp_type': 'fixed'},
    'name': 'momentum_560382f8'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "momentum_560382f8"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
