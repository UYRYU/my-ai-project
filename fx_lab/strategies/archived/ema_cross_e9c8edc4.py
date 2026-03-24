"""自動生成戦略: ema_cross_e9c8edc4"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'long_period': 58, 'short_period': 9, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 15,
                      'be_trigger_pips': 0.2812,
                      'breakeven': 1,
                      'sl_atr_mult': 3.7025,
                      'sl_type': 'atr_mult',
                      'tp_pips': 1.1209,
                      'tp_type': 'fixed'},
    'name': 'ema_cross_e9c8edc4'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_e9c8edc4"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
