"""自動生成戦略: donchian_break_c808e1f8"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'end_hour': 18, 'start_hour': 8, 'type': 'time_filter'}],
    'entry_signal': {'period': 20, 'type': 'donchian_break'},
    'exit_rules': {   'atr_period': 19,
                      'max_bars': 180,
                      'sl_atr_mult': 2.3719,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 2.9928,
                      'tp_type': 'atr_mult',
                      'trail_distance': 0.3214,
                      'trail_type': 'fixed',
                      'trailing': True},
    'name': 'donchian_break_c808e1f8'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "donchian_break_c808e1f8"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
