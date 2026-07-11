"""自動生成戦略: ema_cross_a9610170"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'long_period': 25, 'short_period': 10, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 13,
                      'be_trigger_pips': 0.1676,
                      'breakeven': 1,
                      'max_bars': 227,
                      'reverse_signal_exit': True,
                      'sl_atr_mult': 1.6256,
                      'sl_pips': 0.5803,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.7412,
                      'tp_pips': 0.5147,
                      'tp_type': 'fixed',
                      'trail_distance': 0.3584,
                      'trail_type': 'fixed',
                      'trailing': 1},
    'name': 'ema_cross_a9610170'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_a9610170"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
