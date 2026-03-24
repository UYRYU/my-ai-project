"""自動生成戦略: donchian_break_67ae5630"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'max_atr': 0.6475, 'min_atr': 0.0611, 'type': 'atr_filter'}],
    'entry_signal': {'period': 15, 'type': 'donchian_break'},
    'exit_rules': {   'atr_period': 8,
                      'max_bars': 155,
                      'sl_atr_mult': 0.9539,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 2.9286,
                      'tp_type': 'atr_mult',
                      'trail_distance': 0.2382,
                      'trail_type': 'fixed',
                      'trailing': True},
    'name': 'donchian_break_67ae5630'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "donchian_break_67ae5630"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
