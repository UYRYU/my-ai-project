"""自動生成戦略: rsi_reversal_2673622a"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'period': 74, 'type': 'htf_trend'},
                         {'end_hour': 21, 'start_hour': 8, 'type': 'time_filter'}],
    'entry_signal': {'overbought': 67, 'oversold': 24, 'period': 13, 'type': 'rsi_reversal'},
    'exit_rules': {   'atr_period': 18,
                      'sl_atr_mult': 1.3549,
                      'sl_type': 'atr_mult',
                      'tp_pips': 0.1647,
                      'tp_type': 'fixed'},
    'name': 'rsi_reversal_2673622a'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_reversal_2673622a"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
