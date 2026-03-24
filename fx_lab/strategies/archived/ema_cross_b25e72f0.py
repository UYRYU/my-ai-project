"""自動生成戦略: ema_cross_b25e72f0"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'long_period': 60, 'short_period': 9, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 15,
                      'be_trigger_pips': 0.2346,
                      'breakeven': 2,
                      'sl_atr_mult': 3.8035,
                      'sl_type': 'atr_mult',
                      'tp_pips': 0.9811,
                      'tp_type': 'fixed'},
    'name': 'ema_cross_b25e72f0'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_b25e72f0"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
