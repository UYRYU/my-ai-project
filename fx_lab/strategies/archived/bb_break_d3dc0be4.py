"""自動生成戦略: bb_break_d3dc0be4"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'period': 18, 'std_mult': 1.7401, 'type': 'bb_break'},
    'exit_rules': {   'atr_period': 14,
                      'sl_atr_mult': 2.7193,
                      'sl_type': 'atr_mult',
                      'tp_pips': 0.3084,
                      'tp_type': 'fixed',
                      'trail_distance': 0.1281,
                      'trail_type': 'fixed',
                      'trailing': True},
    'name': 'bb_break_d3dc0be4'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "bb_break_d3dc0be4"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
