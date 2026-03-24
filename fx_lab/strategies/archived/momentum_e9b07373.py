"""自動生成戦略: momentum_e9b07373"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'max_atr': 0.9462, 'min_atr': 0.0867, 'type': 'atr_filter'},
                         {'period': 60, 'type': 'htf_trend'}],
    'entry_signal': {'period': 7, 'type': 'momentum'},
    'exit_rules': {   'atr_period': 14,
                      'reverse_signal_exit': True,
                      'sl_pips': 0.1567,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.5921,
                      'tp_type': 'atr_mult',
                      'trail_distance': 0.2353,
                      'trail_type': 'fixed',
                      'trailing': True},
    'name': 'momentum_e9b07373'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "momentum_e9b07373"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
