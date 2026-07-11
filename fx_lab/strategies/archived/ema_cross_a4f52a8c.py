"""自動生成戦略: ema_cross_a4f52a8c"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'long_period': 35, 'short_period': 6, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 20,
                      'max_bars': 228,
                      'reverse_signal_exit': True,
                      'sl_pips': 0.4409,
                      'sl_type': 'fixed',
                      'tp_pips': 0.5201,
                      'tp_type': 'fixed'},
    'name': 'ema_cross_a4f52a8c'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_a4f52a8c"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
