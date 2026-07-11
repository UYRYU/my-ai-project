"""自動生成戦略: ema_cross_a4bc2fe2"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'long_period': 29, 'short_period': 6, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 20,
                      'be_trigger_pips': 0.2346,
                      'breakeven': 1,
                      'max_bars': 293,
                      'sl_atr_mult': 3.0597,
                      'sl_pips': 0.4409,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 3.4605,
                      'tp_pips': 0.7238,
                      'tp_type': 'fixed'},
    'name': 'ema_cross_a4bc2fe2'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_a4bc2fe2"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
