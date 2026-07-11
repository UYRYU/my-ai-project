"""自動生成戦略: atr_break_099abdaa"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'multiplier': 1.4435, 'period': 12, 'type': 'atr_break'},
    'exit_rules': {   'atr_period': 13,
                      'be_trigger_pips': 0.1126,
                      'breakeven': 2,
                      'sl_pips': 0.2154,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.5246,
                      'tp_type': 'atr_mult',
                      'trail_distance': 0.3046,
                      'trail_type': 'fixed',
                      'trailing': 2},
    'name': 'atr_break_099abdaa'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "atr_break_099abdaa"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
