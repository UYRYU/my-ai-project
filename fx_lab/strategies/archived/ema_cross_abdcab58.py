"""自動生成戦略: ema_cross_abdcab58"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'period': 42, 'type': 'htf_trend'}],
    'entry_signal': {'long_period': 39, 'short_period': 10, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 8,
                      'max_bars': 109,
                      'sl_atr_mult': 1.471,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 2.5386,
                      'tp_type': 'atr_mult',
                      'trail_distance': 0.1307,
                      'trail_type': 'fixed',
                      'trailing': True},
    'name': 'ema_cross_abdcab58'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_abdcab58"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
