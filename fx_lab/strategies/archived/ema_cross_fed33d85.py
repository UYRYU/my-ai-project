"""自動生成戦略: ema_cross_fed33d85"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'max_atr': 0.8297, 'min_atr': 0.0529, 'type': 'atr_filter'},
                         {'period': 89, 'type': 'htf_trend'}],
    'entry_signal': {'long_period': 57, 'short_period': 14, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 17,
                      'sl_atr_mult': 2.61,
                      'sl_type': 'atr_mult',
                      'tp_pips': 0.3281,
                      'tp_type': 'fixed'},
    'name': 'ema_cross_fed33d85'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_fed33d85"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
