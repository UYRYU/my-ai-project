"""自動生成戦略: rsi_trend_e5bdde1a"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'period': 16, 'type': 'rsi_trend'},
    'exit_rules': {   'atr_period': 12,
                      'sl_atr_mult': 2.204,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 2.9834,
                      'tp_type': 'atr_mult'},
    'name': 'rsi_trend_e5bdde1a'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_trend_e5bdde1a"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
