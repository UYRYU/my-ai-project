"""自動生成戦略: rsi_trend_0c37c239"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'max_atr': 0.7548, 'min_atr': 0.0422, 'type': 'atr_filter'},
                         {'period': 98, 'type': 'htf_trend'}],
    'entry_signal': {'period': 14, 'type': 'rsi_trend'},
    'exit_rules': {   'atr_period': 12,
                      'sl_atr_mult': 2.204,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 2.7346,
                      'tp_pips': 0.5431,
                      'tp_type': 'fixed',
                      'trail_atr_mult': 1.0032,
                      'trail_type': 'atr_mult',
                      'trailing': True},
    'name': 'rsi_trend_0c37c239'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_trend_0c37c239"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
