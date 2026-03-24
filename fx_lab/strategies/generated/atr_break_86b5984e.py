"""自動生成戦略: atr_break_86b5984e"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'period': 94, 'type': 'htf_trend'}],
    'entry_signal': {'multiplier': 1.4419, 'period': 10, 'type': 'atr_break'},
    'exit_rules': {   'atr_period': 12,
                      'be_trigger_pips': 0.1531,
                      'breakeven': 2,
                      'max_bars': 247,
                      'sl_atr_mult': 2.3956,
                      'sl_pips': 0.1917,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 2.1381,
                      'tp_pips': 0.6189,
                      'tp_type': 'atr_mult',
                      'trail_distance': 0.3366,
                      'trail_type': 'fixed',
                      'trailing': 2},
    'name': 'atr_break_86b5984e'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "atr_break_86b5984e"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
