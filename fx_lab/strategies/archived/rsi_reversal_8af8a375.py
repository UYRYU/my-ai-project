"""自動生成戦略: rsi_reversal_8af8a375"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'overbought': 68, 'oversold': 35, 'period': 14, 'type': 'rsi_reversal'},
    'exit_rules': {   'atr_period': 17,
                      'sl_atr_mult': 1.9492,
                      'sl_type': 'atr_mult',
                      'tp_pips': 0.3467,
                      'tp_type': 'fixed'},
    'name': 'rsi_reversal_8af8a375'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_reversal_8af8a375"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
