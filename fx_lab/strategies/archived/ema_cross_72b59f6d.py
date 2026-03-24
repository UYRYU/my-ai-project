"""自動生成戦略: ema_cross_72b59f6d"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'max_atr': 0.6921, 'min_atr': 0.0443, 'type': 'atr_filter'},
                         {'period': 94, 'type': 'htf_trend'}],
    'entry_signal': {'long_period': 25, 'short_period': 10, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 20,
                      'be_trigger_pips': 0.2213,
                      'breakeven': True,
                      'max_bars': 239,
                      'sl_atr_mult': 2.204,
                      'sl_pips': 0.5766,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 2.5859,
                      'tp_pips': 0.5431,
                      'tp_type': 'fixed'},
    'name': 'ema_cross_72b59f6d'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_72b59f6d"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
