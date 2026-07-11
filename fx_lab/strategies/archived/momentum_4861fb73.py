"""自動生成戦略: momentum_4861fb73"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'period': 20, 'type': 'momentum'},
    'exit_rules': {   'atr_period': 20,
                      'sl_pips': 0.1574,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.092,
                      'tp_type': 'atr_mult'},
    'name': 'momentum_4861fb73'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "momentum_4861fb73"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
