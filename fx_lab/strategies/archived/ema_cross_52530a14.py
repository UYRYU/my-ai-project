"""自動生成戦略: ema_cross_52530a14"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'end_hour': 21, 'start_hour': 9, 'type': 'time_filter'},
                         {'period': 67, 'type': 'htf_trend'}],
    'entry_signal': {'long_period': 55, 'short_period': 9, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 15,
                      'be_trigger_pips': 0.2464,
                      'breakeven': 2,
                      'sl_atr_mult': 3.7025,
                      'sl_pips': 0.3345,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 3.3569,
                      'tp_pips': 1.051,
                      'tp_type': 'fixed',
                      'trail_atr_mult': 0.8762,
                      'trail_type': 'atr_mult',
                      'trailing': True},
    'name': 'ema_cross_52530a14'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_52530a14"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
