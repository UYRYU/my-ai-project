"""自動生成戦略: momentum_17b05b7d"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'period': 10, 'type': 'momentum'},
    'exit_rules': {   'atr_period': 17,
                      'max_bars': 126,
                      'reverse_signal_exit': True,
                      'sl_pips': 0.4134,
                      'sl_type': 'fixed',
                      'tp_pips': 0.6568,
                      'tp_type': 'fixed'},
    'name': 'momentum_17b05b7d'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "momentum_17b05b7d"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
