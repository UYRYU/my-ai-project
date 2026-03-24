"""自動生成戦略: ema_cross_05fb5502"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'long_period': 31, 'short_period': 6, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 15,
                      'sl_pips': 0.2867,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.2884,
                      'tp_type': 'atr_mult',
                      'trail_atr_mult': 1.7133,
                      'trail_type': 'atr_mult',
                      'trailing': True},
    'name': 'ema_cross_05fb5502'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_05fb5502"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
