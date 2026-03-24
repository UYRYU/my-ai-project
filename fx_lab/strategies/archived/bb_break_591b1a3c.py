"""自動生成戦略: bb_break_591b1a3c"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'period': 62, 'type': 'htf_trend'},
                         {'max_atr': 0.5425, 'min_atr': 0.0787, 'type': 'atr_filter'}],
    'entry_signal': {'period': 29, 'std_mult': 2.2874, 'type': 'bb_break'},
    'exit_rules': {   'atr_period': 15,
                      'sl_atr_mult': 1.5287,
                      'sl_type': 'atr_mult',
                      'tp_pips': 0.2918,
                      'tp_type': 'fixed',
                      'trail_atr_mult': 1.2597,
                      'trail_type': 'atr_mult',
                      'trailing': True},
    'name': 'bb_break_591b1a3c'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "bb_break_591b1a3c"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
