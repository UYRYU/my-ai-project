"""自動生成戦略: ema_cross_f0deb4f0"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'long_period': 33, 'short_period': 10, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 15,
                      'reverse_signal_exit': True,
                      'sl_atr_mult': 1.6296,
                      'sl_pips': 0.3615,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 2.1981,
                      'tp_pips': 0.5033,
                      'tp_type': 'atr_mult'},
    'name': 'ema_cross_f0deb4f0'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_f0deb4f0"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
