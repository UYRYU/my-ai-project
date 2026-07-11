"""自動生成戦略: bb_bounce_030b3388"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'period': 19, 'std_mult': 2.2207, 'type': 'bb_bounce'},
    'exit_rules': {   'atr_period': 7,
                      'reverse_signal_exit': True,
                      'sl_pips': 0.1412,
                      'sl_type': 'fixed',
                      'tp_pips': 0.2875,
                      'tp_type': 'fixed'},
    'name': 'bb_bounce_030b3388'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "bb_bounce_030b3388"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
