"""自動生成戦略: rsi_reversal_1267fc98"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [],
    'entry_signal': {'overbought': 69, 'oversold': 28, 'period': 8, 'type': 'rsi_reversal'},
    'exit_rules': {   'atr_period': 19,
                      'sl_atr_mult': 2.0485,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 2.4687,
                      'tp_type': 'atr_mult',
                      'trail_atr_mult': 1.1908,
                      'trail_type': 'atr_mult',
                      'trailing': True},
    'name': 'rsi_reversal_1267fc98'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_reversal_1267fc98"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
