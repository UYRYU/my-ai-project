"""自動生成戦略: ema_cross_3d0f440e"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'end_hour': 19, 'start_hour': 9, 'type': 'time_filter'}],
    'entry_signal': {'long_period': 37, 'short_period': 2, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 18,
                      'be_trigger_pips': 0.2346,
                      'breakeven': 1,
                      'sl_atr_mult': 1.3254,
                      'sl_pips': 0.3345,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 3.3569,
                      'tp_pips': 0.704,
                      'tp_type': 'atr_mult'},
    'name': 'ema_cross_3d0f440e'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_3d0f440e"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
