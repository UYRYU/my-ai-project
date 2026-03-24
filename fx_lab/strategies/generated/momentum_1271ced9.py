"""自動生成戦略: momentum_1271ced9"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'max_atr': 1.0225, 'min_atr': 0.0422, 'type': 'atr_filter'},
                         {'period': 92, 'type': 'htf_trend'},
                         {'max_atr': 0.9553, 'min_atr': 0.0479, 'type': 'atr_filter'}],
    'entry_signal': {'period': 11, 'type': 'momentum'},
    'exit_rules': {   'atr_period': 10,
                      'sl_atr_mult': 1.8513,
                      'sl_type': 'atr_mult',
                      'tp_pips': 0.7115,
                      'tp_type': 'fixed'},
    'name': 'momentum_1271ced9'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "momentum_1271ced9"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
