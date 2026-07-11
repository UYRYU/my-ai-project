"""自動生成戦略: ema_cross_d92c171c"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'end_hour': 20, 'start_hour': 9, 'type': 'time_filter'}],
    'entry_signal': {'long_period': 51, 'short_period': 10, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 15,
                      'be_trigger_pips': 0.233,
                      'breakeven': True,
                      'max_bars': 233,
                      'sl_atr_mult': 2.8542,
                      'sl_type': 'atr_mult',
                      'tp_pips': 0.7587,
                      'tp_type': 'fixed'},
    'name': 'ema_cross_d92c171c'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_d92c171c"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
