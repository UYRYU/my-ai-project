"""自動生成戦略: bb_break_eda60187"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'period': 15, 'std_mult': 2.349, 'type': 'bb_break'},
    'exit_rules': {   'atr_period': 11,
                      'reverse_signal_exit': True,
                      'sl_atr_mult': 0.5133,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 3.9399,
                      'tp_type': 'atr_mult',
                      'trail_atr_mult': 1.4007,
                      'trail_type': 'atr_mult',
                      'trailing': True},
    'name': 'bb_break_eda60187'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "bb_break_eda60187"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
