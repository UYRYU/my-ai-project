"""自動生成戦略: bb_bounce_855c42e6"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'end_hour': 21, 'start_hour': 8, 'type': 'time_filter'}],
    'entry_signal': {'period': 11, 'std_mult': 1.5665, 'type': 'bb_bounce'},
    'exit_rules': {   'atr_period': 11,
                      'be_trigger_pips': 0.2016,
                      'breakeven': True,
                      'reverse_signal_exit': True,
                      'sl_atr_mult': 0.8393,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 2.4372,
                      'tp_type': 'atr_mult'},
    'name': 'bb_bounce_855c42e6'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "bb_bounce_855c42e6"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
