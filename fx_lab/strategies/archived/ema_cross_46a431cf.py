"""自動生成戦略: ema_cross_46a431cf"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'end_hour': 20, 'start_hour': 8, 'type': 'time_filter'}],
    'entry_signal': {'long_period': 28, 'short_period': 5, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 15,
                      'be_trigger_pips': 0.2265,
                      'breakeven': 2,
                      'max_bars': 248,
                      'sl_atr_mult': 2.8816,
                      'sl_pips': 0.4567,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 3.4605,
                      'tp_pips': 0.7587,
                      'tp_type': 'fixed'},
    'name': 'ema_cross_46a431cf'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_46a431cf"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
