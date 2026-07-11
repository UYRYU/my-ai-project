"""自動生成戦略: rsi_trend_5ab953dc"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'max_atr': 0.7548, 'min_atr': 0.0358, 'type': 'atr_filter'},
                         {'period': 94, 'type': 'htf_trend'},
                         {'max_atr': 0.4628, 'min_atr': 0.0758, 'type': 'atr_filter'}],
    'entry_signal': {'period': 16, 'type': 'rsi_trend'},
    'exit_rules': {   'atr_period': 12,
                      'sl_atr_mult': 2.204,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 2.9368,
                      'tp_pips': 0.5595,
                      'tp_type': 'fixed'},
    'name': 'rsi_trend_5ab953dc'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_trend_5ab953dc"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
