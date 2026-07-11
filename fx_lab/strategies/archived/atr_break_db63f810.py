"""自動生成戦略: atr_break_db63f810"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'multiplier': 1.4419, 'period': 12, 'type': 'atr_break'},
    'exit_rules': {   'atr_period': 15,
                      'be_trigger_pips': 0.168,
                      'breakeven': 2,
                      'max_bars': 247,
                      'sl_atr_mult': 3.9005,
                      'sl_pips': 0.2352,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 2.1381,
                      'tp_pips': 1.1126,
                      'tp_type': 'atr_mult',
                      'trail_distance': 0.362,
                      'trail_type': 'fixed',
                      'trailing': True},
    'name': 'atr_break_db63f810'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "atr_break_db63f810"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
