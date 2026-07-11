"""自動生成戦略: ema_cross_a7af7dce"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'long_period': 25, 'short_period': 9, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 20,
                      'be_trigger_pips': 0.1627,
                      'breakeven': 1,
                      'max_bars': 236,
                      'sl_atr_mult': 1.6256,
                      'sl_pips': 0.5803,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.6445,
                      'tp_pips': 0.5147,
                      'tp_type': 'atr_mult',
                      'trail_distance': 0.356,
                      'trail_type': 'fixed',
                      'trailing': 1},
    'name': 'ema_cross_a7af7dce'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_a7af7dce"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
