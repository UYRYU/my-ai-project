"""自動生成戦略: ema_cross_35788d4c"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'long_period': 24, 'short_period': 9, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 15,
                      'sl_atr_mult': 1.6372,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 1.6189,
                      'tp_type': 'atr_mult',
                      'trail_atr_mult': 1.2924,
                      'trail_type': 'atr_mult',
                      'trailing': True},
    'name': 'ema_cross_35788d4c'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_35788d4c"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
