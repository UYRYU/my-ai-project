"""自動生成戦略: rsi_trend_09b94c3c"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'period': 56, 'type': 'htf_trend'},
                         {'max_atr': 0.356, 'min_atr': 0.0716, 'type': 'atr_filter'}],
    'entry_signal': {'period': 16, 'type': 'rsi_trend'},
    'exit_rules': {   'atr_period': 16,
                      'sl_atr_mult': 1.7346,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 1.7352,
                      'tp_type': 'atr_mult'},
    'name': 'rsi_trend_09b94c3c'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_trend_09b94c3c"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
