"""自動生成戦略: rsi_trend_4e8ecd2c"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'end_hour': 22, 'start_hour': 8, 'type': 'time_filter'}],
    'entry_signal': {'period': 16, 'type': 'rsi_trend'},
    'exit_rules': {   'atr_period': 12,
                      'sl_atr_mult': 2.1601,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 2.5211,
                      'tp_type': 'atr_mult'},
    'name': 'rsi_trend_4e8ecd2c'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_trend_4e8ecd2c"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
