"""自動生成戦略: rsi_reversal_f838aad6"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'period': 90, 'type': 'htf_trend'}],
    'entry_signal': {'overbought': 85, 'oversold': 31, 'period': 18, 'type': 'rsi_reversal'},
    'exit_rules': {   'atr_period': 18,
                      'sl_atr_mult': 2.2293,
                      'sl_pips': 0.3298,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 2.4687,
                      'tp_pips': 0.54,
                      'tp_type': 'atr_mult'},
    'name': 'rsi_reversal_f838aad6'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_reversal_f838aad6"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
