"""自動生成戦略: ema_cross_8927ab63"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'long_period': 19, 'short_period': 9, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 12,
                      'max_bars': 268,
                      'sl_atr_mult': 1.8819,
                      'sl_pips': 0.6336,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.7351,
                      'tp_pips': 0.4664,
                      'tp_type': 'fixed',
                      'trail_atr_mult': 1.4411,
                      'trail_type': 'atr_mult',
                      'trailing': True},
    'name': 'ema_cross_8927ab63'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_8927ab63"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
