"""自動生成戦略: rsi_reversal_12e37f7f"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'end_hour': 21, 'start_hour': 12, 'type': 'time_filter'}],
    'entry_signal': {'overbought': 49, 'oversold': 27, 'period': 26, 'type': 'rsi_reversal'},
    'exit_rules': {   'atr_period': 18,
                      'sl_atr_mult': 1.426,
                      'sl_pips': 0.2407,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 3.4751,
                      'tp_type': 'atr_mult'},
    'name': 'rsi_reversal_12e37f7f'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_reversal_12e37f7f"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
