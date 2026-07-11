"""自動生成戦略: ema_cross_b02e045d"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'end_hour': 18, 'start_hour': 10, 'type': 'time_filter'},
                         {'max_atr': 0.8178, 'min_atr': 0.0733, 'type': 'atr_filter'}],
    'entry_signal': {'long_period': 24, 'short_period': 13, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 10,
                      'be_trigger_pips': 0.2342,
                      'breakeven': True,
                      'max_bars': 193,
                      'sl_pips': 0.1553,
                      'sl_type': 'fixed',
                      'tp_pips': 0.1441,
                      'tp_type': 'fixed'},
    'name': 'ema_cross_b02e045d'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_b02e045d"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
