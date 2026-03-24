"""自動生成戦略: rsi_reversal_93ef9480"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'period': 31, 'type': 'htf_trend'}],
    'entry_signal': {'overbought': 69, 'oversold': 33, 'period': 8, 'type': 'rsi_reversal'},
    'exit_rules': {   'atr_period': 19,
                      'sl_atr_mult': 2.3031,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 2.4817,
                      'tp_type': 'atr_mult',
                      'trail_distance': 0.1467,
                      'trail_type': 'fixed',
                      'trailing': True},
    'name': 'rsi_reversal_93ef9480'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_reversal_93ef9480"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
