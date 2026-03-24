"""自動生成戦略: rsi_trend_e72cd3cf"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'period': 15, 'type': 'rsi_trend'},
    'exit_rules': {   'atr_period': 13,
                      'be_trigger_pips': 0.1742,
                      'breakeven': 1,
                      'sl_atr_mult': 2.9942,
                      'sl_pips': 0.4127,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.7346,
                      'tp_pips': 0.5431,
                      'tp_type': 'atr_mult',
                      'trail_distance': 0.3584,
                      'trail_type': 'fixed',
                      'trailing': 1},
    'name': 'rsi_trend_e72cd3cf'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_trend_e72cd3cf"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
