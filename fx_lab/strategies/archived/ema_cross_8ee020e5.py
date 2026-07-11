"""自動生成戦略: ema_cross_8ee020e5"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'long_period': 35, 'short_period': 1, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 15,
                      'be_trigger_pips': 0.2622,
                      'breakeven': 2,
                      'sl_atr_mult': 2.2049,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 3.4605,
                      'tp_pips': 0.4257,
                      'tp_type': 'fixed'},
    'name': 'ema_cross_8ee020e5'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_8ee020e5"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
