"""自動生成戦略: rsi_trend_2e339403"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'period': 20, 'type': 'rsi_trend'},
    'exit_rules': {   'atr_period': 11,
                      'be_trigger_pips': 0.238,
                      'breakeven': True,
                      'sl_pips': 0.4086,
                      'sl_type': 'fixed',
                      'tp_pips': 0.3254,
                      'tp_type': 'fixed',
                      'trail_distance': 0.1084,
                      'trail_type': 'fixed',
                      'trailing': True},
    'name': 'rsi_trend_2e339403'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_trend_2e339403"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
