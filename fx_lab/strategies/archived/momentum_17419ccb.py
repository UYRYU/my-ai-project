"""自動生成戦略: momentum_17419ccb"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'max_atr': 0.8405, 'min_atr': 0.0108, 'type': 'atr_filter'}],
    'entry_signal': {'period': 10, 'type': 'momentum'},
    'exit_rules': {   'atr_period': 19,
                      'reverse_signal_exit': True,
                      'sl_atr_mult': 2.0705,
                      'sl_type': 'atr_mult',
                      'tp_pips': 0.608,
                      'tp_type': 'fixed',
                      'trail_distance': 0.237,
                      'trail_type': 'fixed',
                      'trailing': True},
    'name': 'momentum_17419ccb'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "momentum_17419ccb"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
