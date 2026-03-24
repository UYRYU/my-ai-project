"""自動生成戦略: momentum_2e7ea40d"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'max_atr': 0.467, 'min_atr': 0.0535, 'type': 'atr_filter'}],
    'entry_signal': {'period': 12, 'type': 'momentum'},
    'exit_rules': {   'atr_period': 14,
                      'sl_atr_mult': 2.3222,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 2.6666,
                      'tp_type': 'atr_mult'},
    'name': 'momentum_2e7ea40d'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "momentum_2e7ea40d"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
