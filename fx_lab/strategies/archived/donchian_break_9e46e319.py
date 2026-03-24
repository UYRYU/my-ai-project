"""自動生成戦略: donchian_break_9e46e319"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'max_atr': 0.8245, 'min_atr': 0.0369, 'type': 'atr_filter'}],
    'entry_signal': {'period': 24, 'type': 'donchian_break'},
    'exit_rules': {   'atr_period': 18,
                      'reverse_signal_exit': True,
                      'sl_atr_mult': 1.2008,
                      'sl_pips': 0.311,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 3.3569,
                      'tp_pips': 0.6693,
                      'tp_type': 'atr_mult'},
    'name': 'donchian_break_9e46e319'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "donchian_break_9e46e319"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
