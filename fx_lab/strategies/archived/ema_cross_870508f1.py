"""自動生成戦略: ema_cross_870508f1"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'period': 31, 'type': 'htf_trend'}],
    'entry_signal': {'long_period': 37, 'short_period': 3, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 15,
                      'be_trigger_pips': 0.2701,
                      'breakeven': 3,
                      'sl_atr_mult': 3.0597,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 3.4605,
                      'tp_pips': 0.7587,
                      'tp_type': 'fixed'},
    'name': 'ema_cross_870508f1'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_870508f1"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
