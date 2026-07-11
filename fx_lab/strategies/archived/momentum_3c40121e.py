"""自動生成戦略: momentum_3c40121e"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'end_hour': 18, 'start_hour': 7, 'type': 'time_filter'}],
    'entry_signal': {'period': 9, 'type': 'momentum'},
    'exit_rules': {   'atr_period': 7,
                      'max_bars': 185,
                      'sl_pips': 0.201,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 1.0748,
                      'tp_type': 'atr_mult'},
    'name': 'momentum_3c40121e'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "momentum_3c40121e"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
