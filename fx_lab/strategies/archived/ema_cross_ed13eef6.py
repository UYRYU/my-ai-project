"""自動生成戦略: ema_cross_ed13eef6"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'max_atr': 0.8023, 'min_atr': 0.0196, 'type': 'atr_filter'}],
    'entry_signal': {'long_period': 19, 'short_period': 9, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 12,
                      'max_bars': 240,
                      'sl_atr_mult': 2.3155,
                      'sl_pips': 0.6336,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 3.0383,
                      'tp_pips': 0.4594,
                      'tp_type': 'fixed'},
    'name': 'ema_cross_ed13eef6'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_ed13eef6"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
