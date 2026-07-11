"""自動生成戦略: atr_break_3670354f"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'multiplier': 1.5282, 'period': 25, 'type': 'atr_break'},
    'exit_rules': {   'atr_period': 13,
                      'be_trigger_pips': 0.1676,
                      'breakeven': 1,
                      'sl_atr_mult': 2.2122,
                      'sl_pips': 0.4127,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 3.3942,
                      'tp_type': 'atr_mult',
                      'trail_atr_mult': 0.689,
                      'trail_distance': 0.2418,
                      'trail_type': 'atr_mult',
                      'trailing': True},
    'name': 'atr_break_3670354f'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "atr_break_3670354f"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
