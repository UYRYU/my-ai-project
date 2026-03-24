"""自動生成戦略: ema_cross_7466a2e2"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'period': 77, 'type': 'htf_trend'}],
    'entry_signal': {'long_period': 25, 'short_period': 11, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 13,
                      'be_trigger_pips': 0.1608,
                      'breakeven': 2,
                      'max_bars': 236,
                      'reverse_signal_exit': True,
                      'sl_atr_mult': 1.6256,
                      'sl_pips': 0.4127,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.664,
                      'tp_pips': 0.59,
                      'tp_type': 'fixed',
                      'trail_distance': 0.3482,
                      'trail_type': 'fixed',
                      'trailing': 3},
    'name': 'ema_cross_7466a2e2'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_7466a2e2"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
