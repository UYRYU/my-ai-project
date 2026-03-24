"""自動生成戦略: rsi_reversal_3fe9f09b"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'overbought': 80, 'oversold': 29, 'period': 19, 'type': 'rsi_reversal'},
    'exit_rules': {   'atr_period': 18,
                      'be_trigger_pips': 0.138,
                      'breakeven': True,
                      'sl_atr_mult': 1.34,
                      'sl_pips': 0.3189,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.4212,
                      'tp_pips': 0.7115,
                      'tp_type': 'fixed'},
    'name': 'rsi_reversal_3fe9f09b'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_reversal_3fe9f09b"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
