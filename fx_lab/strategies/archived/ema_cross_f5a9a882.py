"""自動生成戦略: ema_cross_f5a9a882"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'long_period': 25, 'short_period': 10, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 20,
                      'be_trigger_pips': 0.1414,
                      'breakeven': 3,
                      'max_bars': 298,
                      'sl_atr_mult': 2.4102,
                      'sl_pips': 0.2154,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 2.1381,
                      'tp_pips': 0.6189,
                      'tp_type': 'fixed',
                      'trail_distance': 0.3366,
                      'trail_type': 'fixed',
                      'trailing': True},
    'name': 'ema_cross_f5a9a882'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_f5a9a882"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
