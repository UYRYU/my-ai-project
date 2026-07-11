"""自動生成戦略: donchian_break_2790e9e7"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'period': 44, 'type': 'donchian_break'},
    'exit_rules': {   'atr_period': 14,
                      'be_trigger_pips': 0.1763,
                      'breakeven': True,
                      'sl_pips': 0.238,
                      'sl_type': 'fixed',
                      'tp_pips': 0.5504,
                      'tp_type': 'fixed'},
    'name': 'donchian_break_2790e9e7'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "donchian_break_2790e9e7"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
