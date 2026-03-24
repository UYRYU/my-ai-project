"""自動生成戦略: momentum_3967e139"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'max_atr': 0.7632, 'min_atr': 0.0422, 'type': 'atr_filter'},
                         {'period': 92, 'type': 'htf_trend'}],
    'entry_signal': {'period': 15, 'type': 'momentum'},
    'exit_rules': {   'atr_period': 10,
                      'sl_atr_mult': 1.419,
                      'sl_type': 'atr_mult',
                      'tp_pips': 0.5008,
                      'tp_type': 'fixed'},
    'name': 'momentum_3967e139'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "momentum_3967e139"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
