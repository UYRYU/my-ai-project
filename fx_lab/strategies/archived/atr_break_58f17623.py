"""自動生成戦略: atr_break_58f17623"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'multiplier': 1.3171, 'period': 12, 'type': 'atr_break'},
    'exit_rules': {   'atr_period': 15,
                      'be_trigger_pips': 0.2334,
                      'breakeven': 2,
                      'sl_atr_mult': 3.4925,
                      'sl_pips': 0.2126,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 2.1381,
                      'tp_pips': 1.1209,
                      'tp_type': 'atr_mult',
                      'trail_distance': 0.3444,
                      'trail_type': 'fixed',
                      'trailing': 3},
    'name': 'atr_break_58f17623'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "atr_break_58f17623"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
