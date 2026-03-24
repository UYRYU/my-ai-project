"""自動生成戦略: ema_cross_b6b2965f"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'long_period': 28, 'short_period': 8, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 20,
                      'max_bars': 260,
                      'sl_atr_mult': 1.4621,
                      'sl_pips': 0.3981,
                      'sl_type': 'fixed',
                      'tp_pips': 0.4203,
                      'tp_type': 'fixed'},
    'name': 'ema_cross_b6b2965f'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_b6b2965f"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
