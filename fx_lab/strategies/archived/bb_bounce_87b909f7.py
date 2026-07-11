"""自動生成戦略: bb_bounce_87b909f7"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'period': 18, 'std_mult': 2.1864, 'type': 'bb_bounce'},
    'exit_rules': {   'atr_period': 21,
                      'sl_pips': 0.1037,
                      'sl_type': 'fixed',
                      'tp_pips': 0.561,
                      'tp_type': 'fixed',
                      'trail_distance': 0.3389,
                      'trail_type': 'fixed',
                      'trailing': True},
    'name': 'bb_bounce_87b909f7'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "bb_bounce_87b909f7"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
