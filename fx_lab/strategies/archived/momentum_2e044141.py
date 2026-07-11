"""自動生成戦略: momentum_2e044141"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'period': 16, 'type': 'momentum'},
    'exit_rules': {   'atr_period': 18,
                      'be_trigger_pips': 0.2427,
                      'breakeven': True,
                      'sl_atr_mult': 1.5103,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 2.3402,
                      'tp_type': 'atr_mult'},
    'name': 'momentum_2e044141'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "momentum_2e044141"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
