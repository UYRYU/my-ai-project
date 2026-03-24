"""自動生成戦略: rsi_reversal_de920a1b"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'end_hour': 22, 'start_hour': 8, 'type': 'time_filter'},
                         {'max_atr': 0.5904, 'min_atr': 0.0342, 'type': 'atr_filter'}],
    'entry_signal': {'overbought': 77, 'oversold': 34, 'period': 7, 'type': 'rsi_reversal'},
    'exit_rules': {   'atr_period': 9,
                      'sl_atr_mult': 0.6221,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 3.7135,
                      'tp_type': 'atr_mult'},
    'name': 'rsi_reversal_de920a1b'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_reversal_de920a1b"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
