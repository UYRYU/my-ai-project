"""自動生成戦略: momentum_e740330d"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'max_atr': 1.0225, 'min_atr': 0.0422, 'type': 'atr_filter'},
                         {'period': 92, 'type': 'htf_trend'},
                         {'max_atr': 0.8769, 'min_atr': 0.0479, 'type': 'atr_filter'}],
    'entry_signal': {'period': 19, 'type': 'momentum'},
    'exit_rules': {   'atr_period': 10,
                      'max_bars': 96,
                      'sl_atr_mult': 0.9961,
                      'sl_type': 'atr_mult',
                      'tp_pips': 0.7115,
                      'tp_type': 'fixed'},
    'name': 'momentum_e740330d'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "momentum_e740330d"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
