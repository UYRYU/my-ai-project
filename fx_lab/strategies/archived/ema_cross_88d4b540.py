"""自動生成戦略: ema_cross_88d4b540"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'long_period': 53, 'short_period': 9, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 15,
                      'be_trigger_pips': 0.168,
                      'breakeven': 1,
                      'sl_atr_mult': 1.6359,
                      'sl_type': 'atr_mult',
                      'tp_pips': 0.6256,
                      'tp_type': 'fixed'},
    'name': 'ema_cross_88d4b540'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_88d4b540"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
