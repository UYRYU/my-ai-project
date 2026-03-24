"""自動生成戦略: bb_break_6fc3d727"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'period': 28, 'std_mult': 2.36, 'type': 'bb_break'},
    'exit_rules': {   'atr_period': 13,
                      'reverse_signal_exit': True,
                      'sl_pips': 0.3821,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 1.4668,
                      'tp_type': 'atr_mult',
                      'trail_atr_mult': 1.5545,
                      'trail_type': 'atr_mult',
                      'trailing': True},
    'name': 'bb_break_6fc3d727'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "bb_break_6fc3d727"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
