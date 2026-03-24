"""自動生成戦略: atr_break_44860bf3"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'period': 91, 'type': 'htf_trend'}],
    'entry_signal': {'multiplier': 1.5282, 'period': 28, 'type': 'atr_break'},
    'exit_rules': {   'atr_period': 12,
                      'be_trigger_pips': 0.1676,
                      'breakeven': 2,
                      'max_bars': 247,
                      'reverse_signal_exit': True,
                      'sl_atr_mult': 1.6256,
                      'sl_pips': 0.4068,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.664,
                      'tp_pips': 0.5837,
                      'tp_type': 'atr_mult',
                      'trail_distance': 0.3366,
                      'trail_type': 'fixed',
                      'trailing': 2},
    'name': 'atr_break_44860bf3'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "atr_break_44860bf3"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
