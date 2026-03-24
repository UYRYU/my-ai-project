"""自動生成戦略: atr_break_bb409273"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'period': 38, 'type': 'htf_trend'},
                         {'max_atr': 0.5381, 'min_atr': 0.0748, 'type': 'atr_filter'}],
    'entry_signal': {'multiplier': 1.536, 'period': 11, 'type': 'atr_break'},
    'exit_rules': {   'atr_period': 8,
                      'sl_pips': 0.1316,
                      'sl_type': 'fixed',
                      'tp_pips': 0.1953,
                      'tp_type': 'fixed'},
    'name': 'atr_break_bb409273'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "atr_break_bb409273"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
