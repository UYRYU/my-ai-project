"""自動生成戦略: atr_break_386a6412"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'multiplier': 1.4419, 'period': 21, 'type': 'atr_break'},
    'exit_rules': {   'atr_period': 13,
                      'be_trigger_pips': 0.1676,
                      'breakeven': True,
                      'sl_pips': 0.3829,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.4519,
                      'tp_type': 'atr_mult',
                      'trail_distance': 0.3366,
                      'trail_type': 'fixed',
                      'trailing': True},
    'name': 'atr_break_386a6412'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "atr_break_386a6412"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
