"""自動生成戦略: bb_bounce_4b9af643"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'max_atr': 0.9979, 'min_atr': 0.054, 'type': 'atr_filter'}],
    'entry_signal': {'period': 14, 'std_mult': 2.0327, 'type': 'bb_bounce'},
    'exit_rules': {   'atr_period': 9,
                      'max_bars': 173,
                      'reverse_signal_exit': True,
                      'sl_pips': 0.2274,
                      'sl_type': 'fixed',
                      'tp_pips': 0.4368,
                      'tp_type': 'fixed'},
    'name': 'bb_bounce_4b9af643'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "bb_bounce_4b9af643"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
