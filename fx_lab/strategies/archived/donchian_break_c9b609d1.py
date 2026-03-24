"""自動生成戦略: donchian_break_c9b609d1"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'period': 70, 'type': 'htf_trend'}],
    'entry_signal': {'period': 23, 'type': 'donchian_break'},
    'exit_rules': {   'atr_period': 14,
                      'sl_pips': 0.2394,
                      'sl_type': 'fixed',
                      'tp_pips': 0.4454,
                      'tp_type': 'fixed'},
    'name': 'donchian_break_c9b609d1'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "donchian_break_c9b609d1"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
