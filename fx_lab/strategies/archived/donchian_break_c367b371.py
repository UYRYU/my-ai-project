"""自動生成戦略: donchian_break_c367b371"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'period': 11, 'type': 'donchian_break'},
    'exit_rules': {   'atr_period': 19,
                      'sl_atr_mult': 2.1484,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 1.0372,
                      'tp_type': 'atr_mult'},
    'name': 'donchian_break_c367b371'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "donchian_break_c367b371"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
