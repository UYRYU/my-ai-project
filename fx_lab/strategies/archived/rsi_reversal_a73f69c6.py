"""自動生成戦略: rsi_reversal_a73f69c6"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'period': 65, 'type': 'htf_trend'}, {'period': 37, 'type': 'htf_trend'}],
    'entry_signal': {'overbought': 85, 'oversold': 27, 'period': 19, 'type': 'rsi_reversal'},
    'exit_rules': {   'atr_period': 18,
                      'sl_atr_mult': 1.2864,
                      'sl_pips': 0.3314,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 2.6653,
                      'tp_type': 'atr_mult'},
    'name': 'rsi_reversal_a73f69c6'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_reversal_a73f69c6"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
