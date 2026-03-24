"""自動生成戦略: momentum_1a6eb05d"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'period': 6, 'type': 'momentum'},
    'exit_rules': {   'atr_period': 7,
                      'sl_atr_mult': 1.9482,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 2.0024,
                      'tp_type': 'atr_mult'},
    'name': 'momentum_1a6eb05d'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "momentum_1a6eb05d"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
