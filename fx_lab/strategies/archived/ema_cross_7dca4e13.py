"""自動生成戦略: ema_cross_7dca4e13"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'long_period': 19, 'short_period': 9, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 12,
                      'max_bars': 252,
                      'sl_atr_mult': 2.2127,
                      'sl_pips': 0.6336,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.7241,
                      'tp_pips': 0.4396,
                      'tp_type': 'fixed'},
    'name': 'ema_cross_7dca4e13'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_7dca4e13"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
