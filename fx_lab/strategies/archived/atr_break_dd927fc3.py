"""自動生成戦略: atr_break_dd927fc3"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'period': 56, 'type': 'htf_trend'},
                         {'end_hour': 18, 'start_hour': 9, 'type': 'time_filter'}],
    'entry_signal': {'multiplier': 2.9522, 'period': 8, 'type': 'atr_break'},
    'exit_rules': {   'atr_period': 10,
                      'be_trigger_pips': 0.3144,
                      'breakeven': True,
                      'sl_atr_mult': 0.6718,
                      'sl_type': 'atr_mult',
                      'tp_pips': 0.6916,
                      'tp_type': 'fixed',
                      'trail_distance': 0.1383,
                      'trail_type': 'fixed',
                      'trailing': True},
    'name': 'atr_break_dd927fc3'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "atr_break_dd927fc3"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
