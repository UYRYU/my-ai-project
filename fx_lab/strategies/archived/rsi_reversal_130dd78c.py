"""自動生成戦略: rsi_reversal_130dd78c"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'overbought': 79, 'oversold': 32, 'period': 18, 'type': 'rsi_reversal'},
    'exit_rules': {   'atr_period': 13,
                      'sl_atr_mult': 2.4838,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 1.6453,
                      'tp_type': 'atr_mult'},
    'name': 'rsi_reversal_130dd78c'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_reversal_130dd78c"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
