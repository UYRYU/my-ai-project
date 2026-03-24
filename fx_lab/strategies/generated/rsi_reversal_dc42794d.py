"""自動生成戦略: rsi_reversal_dc42794d"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'period': 73, 'type': 'htf_trend'},
                         {'max_atr': 0.7439, 'min_atr': 0.0437, 'type': 'atr_filter'},
                         {'end_hour': 22, 'start_hour': 7, 'type': 'time_filter'}],
    'entry_signal': {'overbought': 80, 'oversold': 29, 'period': 19, 'type': 'rsi_reversal'},
    'exit_rules': {   'atr_period': 18,
                      'reverse_signal_exit': True,
                      'sl_pips': 0.3627,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.3255,
                      'tp_type': 'atr_mult'},
    'name': 'rsi_reversal_dc42794d'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_reversal_dc42794d"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
