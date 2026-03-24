"""自動生成戦略: donchian_break_505a9d19"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'end_hour': 20, 'start_hour': 7, 'type': 'time_filter'}],
    'entry_signal': {'period': 23, 'type': 'donchian_break'},
    'exit_rules': {   'atr_period': 14,
                      'be_trigger_pips': 0.3006,
                      'breakeven': True,
                      'sl_atr_mult': 0.8775,
                      'sl_type': 'atr_mult',
                      'tp_pips': 0.7758,
                      'tp_type': 'fixed',
                      'trail_distance': 0.1638,
                      'trail_type': 'fixed',
                      'trailing': True},
    'name': 'donchian_break_505a9d19'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "donchian_break_505a9d19"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
