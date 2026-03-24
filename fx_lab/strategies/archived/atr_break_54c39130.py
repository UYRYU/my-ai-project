"""自動生成戦略: atr_break_54c39130"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'multiplier': 1.4643, 'period': 8, 'type': 'atr_break'},
    'exit_rules': {   'atr_period': 9,
                      'reverse_signal_exit': True,
                      'sl_atr_mult': 0.7619,
                      'sl_type': 'atr_mult',
                      'tp_pips': 0.3042,
                      'tp_type': 'fixed',
                      'trail_atr_mult': 1.4435,
                      'trail_type': 'atr_mult',
                      'trailing': True},
    'name': 'atr_break_54c39130'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "atr_break_54c39130"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
