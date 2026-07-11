"""自動生成戦略: bb_break_98255d65"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'end_hour': 18, 'start_hour': 8, 'type': 'time_filter'}],
    'entry_signal': {'period': 15, 'std_mult': 2.3816, 'type': 'bb_break'},
    'exit_rules': {   'atr_period': 7,
                      'be_trigger_pips': 0.1412,
                      'breakeven': True,
                      'sl_atr_mult': 2.0139,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 3.8702,
                      'tp_type': 'atr_mult',
                      'trail_atr_mult': 1.2785,
                      'trail_type': 'atr_mult',
                      'trailing': True},
    'name': 'bb_break_98255d65'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "bb_break_98255d65"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
