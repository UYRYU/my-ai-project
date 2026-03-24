"""自動生成戦略: ema_cross_be6570c3"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'max_atr': 1.0501, 'min_atr': 0.0422, 'type': 'atr_filter'}],
    'entry_signal': {'long_period': 54, 'short_period': 8, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 10,
                      'be_trigger_pips': 0.2463,
                      'breakeven': 1,
                      'sl_atr_mult': 2.8542,
                      'sl_type': 'atr_mult',
                      'tp_pips': 0.8654,
                      'tp_type': 'fixed'},
    'name': 'ema_cross_be6570c3'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_be6570c3"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
