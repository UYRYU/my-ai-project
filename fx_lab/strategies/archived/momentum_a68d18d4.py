"""自動生成戦略: momentum_a68d18d4"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'max_atr': 0.9331, 'min_atr': 0.0422, 'type': 'atr_filter'},
                         {'period': 96, 'type': 'htf_trend'}],
    'entry_signal': {'period': 17, 'type': 'momentum'},
    'exit_rules': {   'atr_period': 18,
                      'sl_atr_mult': 1.4928,
                      'sl_pips': 0.3298,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 2.5253,
                      'tp_pips': 0.7115,
                      'tp_type': 'fixed',
                      'trail_distance': 0.2287,
                      'trail_type': 'fixed',
                      'trailing': True},
    'name': 'momentum_a68d18d4'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "momentum_a68d18d4"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
