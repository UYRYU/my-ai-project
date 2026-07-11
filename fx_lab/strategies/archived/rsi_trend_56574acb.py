"""自動生成戦略: rsi_trend_56574acb"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'max_atr': 0.8206, 'min_atr': 0.0422, 'type': 'atr_filter'},
                         {'period': 94, 'type': 'htf_trend'}],
    'entry_signal': {'period': 16, 'type': 'rsi_trend'},
    'exit_rules': {   'atr_period': 15,
                      'be_trigger_pips': 0.2363,
                      'breakeven': 2,
                      'sl_atr_mult': 3.2683,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 3.4957,
                      'tp_pips': 0.5655,
                      'tp_type': 'fixed'},
    'name': 'rsi_trend_56574acb'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_trend_56574acb"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
