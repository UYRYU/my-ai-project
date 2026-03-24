"""自動生成戦略: ema_cross_941775ee"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'long_period': 61, 'short_period': 9, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 12,
                      'be_trigger_pips': 0.2346,
                      'breakeven': 1,
                      'max_bars': 226,
                      'sl_atr_mult': 2.6501,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 2.7346,
                      'tp_pips': 1.1254,
                      'tp_type': 'fixed'},
    'name': 'ema_cross_941775ee'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_941775ee"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
