"""自動生成戦略: ema_cross_2449f2d6"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'period': 89, 'type': 'htf_trend'}],
    'entry_signal': {'long_period': 41, 'short_period': 7, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 15,
                      'be_trigger_pips': 0.2582,
                      'breakeven': True,
                      'sl_atr_mult': 2.6732,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 2.532,
                      'tp_pips': 0.6149,
                      'tp_type': 'fixed'},
    'name': 'ema_cross_2449f2d6'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_2449f2d6"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
