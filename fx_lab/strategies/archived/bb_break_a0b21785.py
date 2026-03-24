"""自動生成戦略: bb_break_a0b21785"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'period': 27, 'std_mult': 2.4939, 'type': 'bb_break'},
    'exit_rules': {   'atr_period': 21,
                      'be_trigger_pips': 0.1176,
                      'breakeven': True,
                      'sl_pips': 0.2885,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.266,
                      'tp_type': 'atr_mult',
                      'trail_atr_mult': 1.0307,
                      'trail_type': 'atr_mult',
                      'trailing': True},
    'name': 'bb_break_a0b21785'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "bb_break_a0b21785"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
