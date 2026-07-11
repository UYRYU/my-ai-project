"""自動生成戦略: rsi_trend_69a963ca"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'period': 90, 'type': 'htf_trend'}],
    'entry_signal': {'period': 16, 'type': 'rsi_trend'},
    'exit_rules': {   'atr_period': 10,
                      'sl_atr_mult': 2.204,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 2.6377,
                      'tp_pips': 0.4525,
                      'tp_type': 'fixed'},
    'name': 'rsi_trend_69a963ca'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_trend_69a963ca"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
