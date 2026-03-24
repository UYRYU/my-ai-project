"""自動生成戦略: rsi_trend_d066d7d9"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'period': 15, 'type': 'rsi_trend'},
    'exit_rules': {   'atr_period': 18,
                      'sl_atr_mult': 2.1132,
                      'sl_pips': 0.3331,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 2.4343,
                      'tp_type': 'atr_mult'},
    'name': 'rsi_trend_d066d7d9'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_trend_d066d7d9"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
