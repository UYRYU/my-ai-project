"""自動生成戦略: donchian_break_f0f876e3"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'max_atr': 0.8737, 'min_atr': 0.0369, 'type': 'atr_filter'}],
    'entry_signal': {'period': 25, 'type': 'donchian_break'},
    'exit_rules': {   'atr_period': 18,
                      'sl_atr_mult': 1.154,
                      'sl_pips': 0.3345,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 3.3182,
                      'tp_pips': 0.675,
                      'tp_type': 'atr_mult'},
    'name': 'donchian_break_f0f876e3'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "donchian_break_f0f876e3"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
