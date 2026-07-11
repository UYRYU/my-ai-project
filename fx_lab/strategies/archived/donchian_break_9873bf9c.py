"""自動生成戦略: donchian_break_9873bf9c"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'max_atr': 0.341, 'min_atr': 0.091, 'type': 'atr_filter'},
                         {'period': 65, 'type': 'htf_trend'}],
    'entry_signal': {'period': 29, 'type': 'donchian_break'},
    'exit_rules': {   'atr_period': 21,
                      'be_trigger_pips': 0.3307,
                      'breakeven': True,
                      'reverse_signal_exit': True,
                      'sl_pips': 0.2142,
                      'sl_type': 'fixed',
                      'tp_pips': 0.5793,
                      'tp_type': 'fixed'},
    'name': 'donchian_break_9873bf9c'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "donchian_break_9873bf9c"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
