"""自動生成戦略: rsi_reversal_f30f6b6d"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'period': 104, 'type': 'htf_trend'},
                         {'max_atr': 0.764, 'min_atr': 0.0257, 'type': 'atr_filter'}],
    'entry_signal': {'overbought': 80, 'oversold': 27, 'period': 10, 'type': 'rsi_reversal'},
    'exit_rules': {   'atr_period': 18,
                      'reverse_signal_exit': 2,
                      'sl_pips': 0.4669,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.6259,
                      'tp_type': 'atr_mult'},
    'name': 'rsi_reversal_f30f6b6d'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_reversal_f30f6b6d"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
