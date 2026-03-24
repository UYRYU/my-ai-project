"""自動生成戦略: momentum_f869c0e8"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'max_atr': 0.8101, 'min_atr': 0.0493, 'type': 'atr_filter'}],
    'entry_signal': {'period': 17, 'type': 'momentum'},
    'exit_rules': {   'atr_period': 10,
                      'sl_atr_mult': 1.419,
                      'sl_pips': 0.3112,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 2.7732,
                      'tp_pips': 0.7115,
                      'tp_type': 'atr_mult'},
    'name': 'momentum_f869c0e8'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "momentum_f869c0e8"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
