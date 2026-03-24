"""自動生成戦略: ema_cross_4d19e2c3"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'period': 53, 'type': 'htf_trend'}, {'period': 59, 'type': 'htf_trend'}],
    'entry_signal': {'long_period': 19, 'short_period': 10, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 20,
                      'be_trigger_pips': 0.1508,
                      'breakeven': 2,
                      'max_bars': 222,
                      'sl_pips': 0.6964,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.1381,
                      'tp_pips': 0.5147,
                      'tp_type': 'fixed',
                      'trail_distance': 0.3439,
                      'trail_type': 'fixed',
                      'trailing': 1},
    'name': 'ema_cross_4d19e2c3'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_4d19e2c3"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
