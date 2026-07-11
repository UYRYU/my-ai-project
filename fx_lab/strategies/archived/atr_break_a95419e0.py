"""自動生成戦略: atr_break_a95419e0"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'period': 81, 'type': 'htf_trend'}],
    'entry_signal': {'multiplier': 1.3768, 'period': 21, 'type': 'atr_break'},
    'exit_rules': {   'atr_period': 13,
                      'be_trigger_pips': 0.1349,
                      'breakeven': 3,
                      'sl_atr_mult': 2.159,
                      'sl_pips': 0.4127,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.7412,
                      'tp_type': 'atr_mult',
                      'trail_distance': 0.3366,
                      'trail_type': 'fixed',
                      'trailing': 2},
    'name': 'atr_break_a95419e0'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "atr_break_a95419e0"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
