"""自動生成戦略: donchian_break_a79cad69"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'period': 60, 'type': 'htf_trend'}],
    'entry_signal': {'period': 39, 'type': 'donchian_break'},
    'exit_rules': {   'atr_period': 10,
                      'max_bars': 113,
                      'sl_atr_mult': 0.7694,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 1.8389,
                      'tp_type': 'atr_mult',
                      'trail_distance': 0.2201,
                      'trail_type': 'fixed',
                      'trailing': True},
    'name': 'donchian_break_a79cad69'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "donchian_break_a79cad69"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
