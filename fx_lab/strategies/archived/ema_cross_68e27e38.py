"""自動生成戦略: ema_cross_68e27e38"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'long_period': 102, 'short_period': 6, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 15,
                      'be_trigger_pips': 0.2334,
                      'breakeven': 3,
                      'sl_atr_mult': 3.7592,
                      'sl_type': 'atr_mult',
                      'tp_pips': 0.7022,
                      'tp_type': 'fixed'},
    'name': 'ema_cross_68e27e38'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_68e27e38"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
