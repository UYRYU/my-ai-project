"""自動生成戦略: ema_cross_98462434"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'long_period': 37, 'short_period': 2, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 15,
                      'be_trigger_pips': 0.2375,
                      'breakeven': 2,
                      'sl_atr_mult': 3.0597,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 3.6138,
                      'tp_pips': 0.7587,
                      'tp_type': 'fixed',
                      'trail_distance': 0.2321,
                      'trail_type': 'fixed',
                      'trailing': True},
    'name': 'ema_cross_98462434'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_98462434"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
