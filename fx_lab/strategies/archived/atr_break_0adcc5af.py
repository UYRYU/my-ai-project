"""自動生成戦略: atr_break_0adcc5af"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'multiplier': 2.0931, 'period': 17, 'type': 'atr_break'},
    'exit_rules': {   'atr_period': 7,
                      'be_trigger_pips': 0.1573,
                      'breakeven': True,
                      'sl_atr_mult': 2.2933,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 1.6401,
                      'tp_type': 'atr_mult'},
    'name': 'atr_break_0adcc5af'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "atr_break_0adcc5af"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
