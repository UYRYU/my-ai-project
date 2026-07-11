"""自動生成戦略: rsi_reversal_2b0309c5"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'max_atr': 0.8481, 'min_atr': 0.0311, 'type': 'atr_filter'},
                         {'period': 73, 'type': 'htf_trend'}],
    'entry_signal': {'overbought': 73, 'oversold': 31, 'period': 8, 'type': 'rsi_reversal'},
    'exit_rules': {   'atr_period': 14,
                      'sl_atr_mult': 2.9319,
                      'sl_type': 'atr_mult',
                      'tp_pips': 0.4691,
                      'tp_type': 'fixed',
                      'trail_distance': 0.1005,
                      'trail_type': 'fixed',
                      'trailing': True},
    'name': 'rsi_reversal_2b0309c5'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_reversal_2b0309c5"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
