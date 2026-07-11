"""自動生成戦略: momentum_4a0db205"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'max_atr': 0.769, 'min_atr': 0.0414, 'type': 'atr_filter'},
                         {'period': 92, 'type': 'htf_trend'}],
    'entry_signal': {'period': 18, 'type': 'momentum'},
    'exit_rules': {   'atr_period': 10,
                      'be_trigger_pips': 0.1119,
                      'breakeven': True,
                      'sl_atr_mult': 1.419,
                      'sl_type': 'atr_mult',
                      'tp_pips': 0.5218,
                      'tp_type': 'fixed'},
    'name': 'momentum_4a0db205'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "momentum_4a0db205"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
