"""自動生成戦略: momentum_5a6bc941"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'period': 15, 'type': 'momentum'},
    'exit_rules': {   'atr_period': 16,
                      'sl_pips': 0.4494,
                      'sl_type': 'fixed',
                      'tp_pips': 0.1352,
                      'tp_type': 'fixed'},
    'name': 'momentum_5a6bc941'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "momentum_5a6bc941"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
