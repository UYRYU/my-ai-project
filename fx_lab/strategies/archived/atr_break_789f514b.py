"""自動生成戦略: atr_break_789f514b"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'multiplier': 1.5769, 'period': 24, 'type': 'atr_break'},
    'exit_rules': {   'atr_period': 13,
                      'be_trigger_pips': 0.1763,
                      'breakeven': 2,
                      'max_bars': 214,
                      'sl_atr_mult': 2.3982,
                      'sl_pips': 0.4409,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.7412,
                      'tp_pips': 0.509,
                      'tp_type': 'atr_mult',
                      'trail_distance': 0.3625,
                      'trail_type': 'fixed',
                      'trailing': 1},
    'name': 'atr_break_789f514b'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "atr_break_789f514b"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
