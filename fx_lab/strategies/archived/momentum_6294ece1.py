"""自動生成戦略: momentum_6294ece1"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'max_atr': 0.9048, 'min_atr': 0.0467, 'type': 'atr_filter'},
                         {'end_hour': 21, 'start_hour': 9, 'type': 'time_filter'}],
    'entry_signal': {'period': 9, 'type': 'momentum'},
    'exit_rules': {   'atr_period': 9,
                      'sl_pips': 0.4188,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 3.6864,
                      'tp_type': 'atr_mult',
                      'trail_distance': 0.1983,
                      'trail_type': 'fixed',
                      'trailing': True},
    'name': 'momentum_6294ece1'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "momentum_6294ece1"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
