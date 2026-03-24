"""自動生成戦略: rsi_reversal_c0995ed3"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'overbought': 72, 'oversold': 29, 'period': 19, 'type': 'rsi_reversal'},
    'exit_rules': {   'atr_period': 18,
                      'sl_pips': 0.3129,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.5805,
                      'tp_pips': 0.5716,
                      'tp_type': 'atr_mult'},
    'name': 'rsi_reversal_c0995ed3'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_reversal_c0995ed3"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
