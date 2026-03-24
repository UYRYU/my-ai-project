"""自動生成戦略: ema_cross_99ed21ec"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'long_period': 50, 'short_period': 9, 'type': 'ema_cross'},
    'exit_rules': {   'atr_period': 15,
                      'be_trigger_pips': 0.2463,
                      'breakeven': 2,
                      'sl_atr_mult': 2.8542,
                      'sl_pips': 0.3115,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.5668,
                      'tp_pips': 0.5503,
                      'tp_type': 'atr_mult'},
    'name': 'ema_cross_99ed21ec'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "ema_cross_99ed21ec"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
