"""自動生成戦略: ema_cross_89d67c6f"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'end_hour': 23, 'start_hour': 9, 'type': 'time_filter'}],
    'entry_signal': {'long_period': 76, 'short_period': 11, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 15,
                      'be_trigger_pips': 0.2334,
                      'breakeven': 2,
                      'sl_atr_mult': 3.5621,
                      'sl_type': 'atr_mult',
                      'tp_pips': 1.0659,
                      'tp_type': 'fixed',
                      'trail_atr_mult': 0.6987,
                      'trail_type': 'atr_mult',
                      'trailing': True},
    'name': 'ema_cross_89d67c6f'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_89d67c6f"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
