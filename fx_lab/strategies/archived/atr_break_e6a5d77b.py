"""自動生成戦略: atr_break_e6a5d77b"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'end_hour': 19, 'start_hour': 7, 'type': 'time_filter'}],
    'entry_signal': {'multiplier': 1.4419, 'period': 11, 'type': 'atr_break'},
    'exit_rules': {   'atr_period': 13,
                      'be_trigger_pips': 0.2346,
                      'breakeven': 2,
                      'sl_atr_mult': 3.7025,
                      'sl_pips': 0.2154,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.1381,
                      'tp_pips': 1.1209,
                      'tp_type': 'fixed',
                      'trail_distance': 0.3366,
                      'trail_type': 'fixed',
                      'trailing': 2},
    'name': 'atr_break_e6a5d77b'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "atr_break_e6a5d77b"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
