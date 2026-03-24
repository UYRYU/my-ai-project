"""自動生成戦略: rsi_reversal_1361b9e1"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'period': 90, 'type': 'htf_trend'}],
    'entry_signal': {'overbought': 69, 'oversold': 28, 'period': 7, 'type': 'rsi_reversal'},
    'exit_rules': {   'atr_period': 19,
                      'sl_atr_mult': 2.3031,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 2.4687,
                      'tp_type': 'atr_mult'},
    'name': 'rsi_reversal_1361b9e1'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_reversal_1361b9e1"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
