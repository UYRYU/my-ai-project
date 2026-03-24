"""自動生成戦略: donchian_break_6a4f8677"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'period': 74, 'type': 'htf_trend'}],
    'entry_signal': {'period': 44, 'type': 'donchian_break'},
    'exit_rules': {   'atr_period': 14,
                      'sl_pips': 0.2966,
                      'sl_type': 'fixed',
                      'tp_pips': 0.5168,
                      'tp_type': 'fixed'},
    'name': 'donchian_break_6a4f8677'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "donchian_break_6a4f8677"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
