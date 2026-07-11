"""自動生成戦略: ema_cross_b7949c3c"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'end_hour': 19, 'start_hour': 7, 'type': 'time_filter'}],
    'entry_signal': {'long_period': 37, 'short_period': 2, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 15,
                      'be_trigger_pips': 0.2346,
                      'breakeven': 2,
                      'sl_atr_mult': 3.7518,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 3.4605,
                      'tp_pips': 0.8199,
                      'tp_type': 'fixed'},
    'name': 'ema_cross_b7949c3c'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_b7949c3c"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
