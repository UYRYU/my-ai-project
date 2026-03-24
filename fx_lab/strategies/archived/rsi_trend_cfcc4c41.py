"""自動生成戦略: rsi_trend_cfcc4c41"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'end_hour': 21, 'start_hour': 8, 'type': 'time_filter'},
                         {'period': 43, 'type': 'htf_trend'}],
    'entry_signal': {'period': 10, 'type': 'rsi_trend'},
    'exit_rules': {   'atr_period': 8,
                      'be_trigger_pips': 0.287,
                      'breakeven': True,
                      'sl_pips': 0.1584,
                      'sl_type': 'fixed',
                      'tp_pips': 0.6372,
                      'tp_type': 'fixed'},
    'name': 'rsi_trend_cfcc4c41'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_trend_cfcc4c41"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
