"""自動生成戦略: ema_cross_1426d360"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'long_period': 27, 'short_period': 15, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 16,
                      'max_bars': 55,
                      'sl_atr_mult': 2.305,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 3.3577,
                      'tp_type': 'atr_mult',
                      'trail_distance': 0.1092,
                      'trail_type': 'fixed',
                      'trailing': True},
    'name': 'ema_cross_1426d360'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_1426d360"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
