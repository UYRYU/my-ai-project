"""自動生成戦略: bb_bounce_c1934f40"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'max_atr': 0.6057, 'min_atr': 0.0248, 'type': 'atr_filter'}],
    'entry_signal': {'period': 27, 'std_mult': 1.6248, 'type': 'bb_bounce'},
    'exit_rules': {   'atr_period': 16,
                      'max_bars': 218,
                      'sl_atr_mult': 2.9917,
                      'sl_type': 'atr_mult',
                      'tp_pips': 0.1748,
                      'tp_type': 'fixed',
                      'trail_distance': 0.2433,
                      'trail_type': 'fixed',
                      'trailing': True},
    'name': 'bb_bounce_c1934f40'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "bb_bounce_c1934f40"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
