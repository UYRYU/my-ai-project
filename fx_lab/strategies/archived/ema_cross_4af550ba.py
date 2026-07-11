"""自動生成戦略: ema_cross_4af550ba"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'period': 63, 'type': 'htf_trend'}],
    'entry_signal': {'long_period': 32, 'short_period': 11, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 13,
                      'be_trigger_pips': 0.1698,
                      'breakeven': True,
                      'reverse_signal_exit': 1,
                      'sl_atr_mult': 1.6296,
                      'sl_pips': 0.3754,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 2.4519,
                      'tp_pips': 0.5415,
                      'tp_type': 'atr_mult',
                      'trail_distance': 0.3366,
                      'trail_type': 'fixed',
                      'trailing': 2},
    'name': 'ema_cross_4af550ba'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_4af550ba"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
