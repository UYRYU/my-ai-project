"""自動生成戦略: ema_cross_c0bc017b"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'long_period': 53, 'short_period': 15, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 7,
                      'be_trigger_pips': 0.185,
                      'breakeven': True,
                      'sl_pips': 0.1899,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 3.2247,
                      'tp_type': 'atr_mult',
                      'trail_distance': 0.2339,
                      'trail_type': 'fixed',
                      'trailing': True},
    'name': 'ema_cross_c0bc017b'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_c0bc017b"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
