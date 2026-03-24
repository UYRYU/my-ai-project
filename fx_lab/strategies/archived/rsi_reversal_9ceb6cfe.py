"""自動生成戦略: rsi_reversal_9ceb6cfe"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'period': 65, 'type': 'htf_trend'},
                         {'max_atr': 0.764, 'min_atr': 0.0437, 'type': 'atr_filter'}],
    'entry_signal': {'overbought': 67, 'oversold': 29, 'period': 19, 'type': 'rsi_reversal'},
    'exit_rules': {   'atr_period': 18,
                      'sl_pips': 0.3345,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.3255,
                      'tp_type': 'atr_mult'},
    'name': 'rsi_reversal_9ceb6cfe'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_reversal_9ceb6cfe"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
