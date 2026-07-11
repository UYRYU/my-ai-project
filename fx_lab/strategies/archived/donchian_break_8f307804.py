"""自動生成戦略: donchian_break_8f307804"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'period': 94, 'type': 'htf_trend'}],
    'entry_signal': {'period': 38, 'type': 'donchian_break'},
    'exit_rules': {   'atr_period': 14,
                      'reverse_signal_exit': True,
                      'sl_pips': 0.2394,
                      'sl_type': 'fixed',
                      'tp_pips': 0.5399,
                      'tp_type': 'fixed'},
    'name': 'donchian_break_8f307804'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "donchian_break_8f307804"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
