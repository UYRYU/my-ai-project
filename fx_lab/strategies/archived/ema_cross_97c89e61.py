"""自動生成戦略: ema_cross_97c89e61"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'long_period': 53, 'short_period': 9, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 15,
                      'be_trigger_pips': 0.2544,
                      'breakeven': True,
                      'max_bars': 228,
                      'sl_atr_mult': 2.8542,
                      'sl_pips': 0.4409,
                      'sl_type': 'fixed',
                      'tp_pips': 0.7587,
                      'tp_type': 'fixed'},
    'name': 'ema_cross_97c89e61'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_97c89e61"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
