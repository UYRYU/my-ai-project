"""自動生成戦略: ema_cross_66822117"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'period': 69, 'type': 'htf_trend'}],
    'entry_signal': {'long_period': 30, 'short_period': 10, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 15,
                      'reverse_signal_exit': True,
                      'sl_atr_mult': 1.8875,
                      'sl_type': 'atr_mult',
                      'tp_pips': 0.5033,
                      'tp_type': 'fixed'},
    'name': 'ema_cross_66822117'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_66822117"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
