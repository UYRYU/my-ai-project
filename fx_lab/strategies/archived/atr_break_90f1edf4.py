"""自動生成戦略: atr_break_90f1edf4"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'period': 92, 'type': 'htf_trend'}],
    'entry_signal': {'multiplier': 1.6499, 'period': 23, 'type': 'atr_break'},
    'exit_rules': {   'atr_period': 13,
                      'be_trigger_pips': 0.1958,
                      'breakeven': 2,
                      'sl_atr_mult': 2.204,
                      'sl_pips': 0.5118,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 3.3147,
                      'tp_type': 'atr_mult',
                      'trail_distance': 0.3366,
                      'trail_type': 'fixed',
                      'trailing': 1},
    'name': 'atr_break_90f1edf4'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "atr_break_90f1edf4"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
