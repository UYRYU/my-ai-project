"""自動生成戦略: atr_break_fe208db7"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'end_hour': 22, 'start_hour': 10, 'type': 'time_filter'}],
    'entry_signal': {'multiplier': 1.4267, 'period': 25, 'type': 'atr_break'},
    'exit_rules': {   'atr_period': 15,
                      'be_trigger_pips': 0.1873,
                      'breakeven': 3,
                      'reverse_signal_exit': 2,
                      'sl_atr_mult': 3.6291,
                      'sl_pips': 0.4673,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.887,
                      'tp_pips': 1.1209,
                      'tp_type': 'atr_mult',
                      'trail_distance': 0.2623,
                      'trail_type': 'fixed',
                      'trailing': True},
    'name': 'atr_break_fe208db7'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "atr_break_fe208db7"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
