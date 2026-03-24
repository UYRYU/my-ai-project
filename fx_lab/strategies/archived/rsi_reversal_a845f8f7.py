"""自動生成戦略: rsi_reversal_a845f8f7"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'period': 65, 'type': 'htf_trend'},
                         {'max_atr': 0.4038, 'min_atr': 0.0394, 'type': 'atr_filter'}],
    'entry_signal': {'overbought': 80, 'oversold': 24, 'period': 20, 'type': 'rsi_reversal'},
    'exit_rules': {   'atr_period': 18,
                      'sl_pips': 0.433,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.6759,
                      'tp_type': 'atr_mult'},
    'name': 'rsi_reversal_a845f8f7'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_reversal_a845f8f7"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
