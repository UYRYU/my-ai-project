"""自動生成戦略: rsi_reversal_d63b314d"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'max_atr': 0.5546, 'min_atr': 0.0523, 'type': 'atr_filter'}],
    'entry_signal': {'overbought': 73, 'oversold': 32, 'period': 11, 'type': 'rsi_reversal'},
    'exit_rules': {   'atr_period': 15,
                      'sl_pips': 0.1262,
                      'sl_type': 'fixed',
                      'tp_pips': 0.2066,
                      'tp_type': 'fixed'},
    'name': 'rsi_reversal_d63b314d'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_reversal_d63b314d"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
