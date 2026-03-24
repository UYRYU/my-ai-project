"""自動生成戦略: atr_break_d1598998"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'period': 116, 'type': 'htf_trend'},
                         {'max_atr': 0.9951, 'min_atr': 0.0491, 'type': 'atr_filter'}],
    'entry_signal': {'multiplier': 1.4946, 'period': 23, 'type': 'atr_break'},
    'exit_rules': {   'atr_period': 12,
                      'be_trigger_pips': 0.1821,
                      'breakeven': 2,
                      'reverse_signal_exit': 3,
                      'sl_atr_mult': 3.0281,
                      'sl_pips': 0.4127,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 2.8386,
                      'tp_pips': 0.5431,
                      'tp_type': 'atr_mult',
                      'trail_distance': 0.3215,
                      'trail_type': 'fixed',
                      'trailing': 1},
    'name': 'atr_break_d1598998'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "atr_break_d1598998"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
