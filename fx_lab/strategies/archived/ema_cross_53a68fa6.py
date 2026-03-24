"""自動生成戦略: ema_cross_53a68fa6"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'period': 89, 'type': 'htf_trend'},
                         {'end_hour': 21, 'start_hour': 8, 'type': 'time_filter'}],
    'entry_signal': {'long_period': 50, 'short_period': 9, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 15,
                      'be_trigger_pips': 0.2553,
                      'breakeven': True,
                      'reverse_signal_exit': True,
                      'sl_atr_mult': 2.8386,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 2.1291,
                      'tp_pips': 0.5896,
                      'tp_type': 'fixed'},
    'name': 'ema_cross_53a68fa6'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_53a68fa6"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
