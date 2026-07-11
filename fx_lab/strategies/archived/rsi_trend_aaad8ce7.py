"""自動生成戦略: rsi_trend_aaad8ce7"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'end_hour': 19, 'start_hour': 10, 'type': 'time_filter'}],
    'entry_signal': {'period': 7, 'type': 'rsi_trend'},
    'exit_rules': {   'atr_period': 10,
                      'be_trigger_pips': 0.1482,
                      'breakeven': True,
                      'max_bars': 80,
                      'sl_pips': 0.1126,
                      'sl_type': 'fixed',
                      'tp_pips': 0.2498,
                      'tp_type': 'fixed'},
    'name': 'rsi_trend_aaad8ce7'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_trend_aaad8ce7"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
