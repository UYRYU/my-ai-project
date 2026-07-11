"""自動生成戦略: donchian_break_c3e2df3a"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'period': 15, 'type': 'donchian_break'},
    'exit_rules': {   'atr_period': 17,
                      'reverse_signal_exit': True,
                      'sl_pips': 0.2377,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 1.6247,
                      'tp_type': 'atr_mult'},
    'name': 'donchian_break_c3e2df3a'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "donchian_break_c3e2df3a"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
