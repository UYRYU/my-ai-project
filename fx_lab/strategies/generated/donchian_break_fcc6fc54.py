"""自動生成戦略: donchian_break_fcc6fc54"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'max_atr': 0.8256, 'min_atr': 0.0369, 'type': 'atr_filter'},
                         {'end_hour': 20, 'start_hour': 7, 'type': 'time_filter'}],
    'entry_signal': {'period': 20, 'type': 'donchian_break'},
    'exit_rules': {   'atr_period': 10,
                      'sl_atr_mult': 1.7027,
                      'sl_type': 'atr_mult',
                      'tp_pips': 0.7225,
                      'tp_type': 'fixed'},
    'name': 'donchian_break_fcc6fc54'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "donchian_break_fcc6fc54"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
