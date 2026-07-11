"""自動生成戦略: donchian_break_88941f39"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'period': 18, 'type': 'donchian_break'},
    'exit_rules': {   'atr_period': 17,
                      'reverse_signal_exit': True,
                      'sl_atr_mult': 1.4965,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 1.5324,
                      'tp_type': 'atr_mult'},
    'name': 'donchian_break_88941f39'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "donchian_break_88941f39"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
