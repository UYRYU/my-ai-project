"""自動生成戦略: momentum_31690f5b"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'period': 18, 'type': 'momentum'},
    'exit_rules': {   'atr_period': 19,
                      'sl_pips': 0.2169,
                      'sl_type': 'fixed',
                      'tp_pips': 0.3472,
                      'tp_type': 'fixed'},
    'name': 'momentum_31690f5b'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "momentum_31690f5b"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
