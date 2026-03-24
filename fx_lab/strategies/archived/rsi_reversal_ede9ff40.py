"""自動生成戦略: rsi_reversal_ede9ff40"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'period': 65, 'type': 'htf_trend'},
                         {'max_atr': 0.764, 'min_atr': 0.0493, 'type': 'atr_filter'}],
    'entry_signal': {'overbought': 83, 'oversold': 29, 'period': 21, 'type': 'rsi_reversal'},
    'exit_rules': {   'atr_period': 18,
                      'sl_pips': 0.3072,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.6217,
                      'tp_type': 'atr_mult'},
    'name': 'rsi_reversal_ede9ff40'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_reversal_ede9ff40"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
