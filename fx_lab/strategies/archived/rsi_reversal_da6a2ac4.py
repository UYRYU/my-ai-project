"""自動生成戦略: rsi_reversal_da6a2ac4"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'overbought': 47, 'oversold': 33, 'period': 8, 'type': 'rsi_reversal'},
    'exit_rules': {   'atr_period': 19,
                      'sl_atr_mult': 1.7809,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 1.8429,
                      'tp_type': 'atr_mult'},
    'name': 'rsi_reversal_da6a2ac4'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_reversal_da6a2ac4"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
