"""自動生成戦略: rsi_trend_d93f8fad"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'max_atr': 0.681, 'min_atr': 0.0834, 'type': 'atr_filter'},
                         {'end_hour': 20, 'start_hour': 7, 'type': 'time_filter'}],
    'entry_signal': {'period': 13, 'type': 'rsi_trend'},
    'exit_rules': {   'atr_period': 11,
                      'max_bars': 93,
                      'sl_atr_mult': 1.7081,
                      'sl_type': 'atr_mult',
                      'tp_pips': 0.4028,
                      'tp_type': 'fixed',
                      'trail_atr_mult': 0.7284,
                      'trail_type': 'atr_mult',
                      'trailing': True},
    'name': 'rsi_trend_d93f8fad'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_trend_d93f8fad"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
