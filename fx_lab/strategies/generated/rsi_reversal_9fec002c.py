"""自動生成戦略: rsi_reversal_9fec002c"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'end_hour': 21, 'start_hour': 9, 'type': 'time_filter'},
                         {'max_atr': 0.467, 'min_atr': 0.059, 'type': 'atr_filter'}],
    'entry_signal': {'overbought': 88, 'oversold': 29, 'period': 19, 'type': 'rsi_reversal'},
    'exit_rules': {   'atr_period': 18,
                      'sl_atr_mult': 2.5183,
                      'sl_pips': 0.3345,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 2.8904,
                      'tp_type': 'atr_mult'},
    'name': 'rsi_reversal_9fec002c'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_reversal_9fec002c"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
