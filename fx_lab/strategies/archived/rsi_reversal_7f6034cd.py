"""自動生成戦略: rsi_reversal_7f6034cd"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'period': 44, 'type': 'htf_trend'},
                         {'max_atr': 0.764, 'min_atr': 0.0599, 'type': 'atr_filter'},
                         {'max_atr': 0.6761, 'min_atr': 0.0357, 'type': 'atr_filter'}],
    'entry_signal': {'overbought': 80, 'oversold': 29, 'period': 19, 'type': 'rsi_reversal'},
    'exit_rules': {   'atr_period': 18,
                      'sl_pips': 0.3879,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.4343,
                      'tp_type': 'atr_mult',
                      'trail_distance': 0.1114,
                      'trail_type': 'fixed',
                      'trailing': True},
    'name': 'rsi_reversal_7f6034cd'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_reversal_7f6034cd"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
