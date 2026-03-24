"""自動生成戦略: rsi_reversal_e47d038f"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'period': 81, 'type': 'htf_trend'},
                         {'max_atr': 0.9381, 'min_atr': 0.0437, 'type': 'atr_filter'}],
    'entry_signal': {'overbought': 79, 'oversold': 27, 'period': 19, 'type': 'rsi_reversal'},
    'exit_rules': {   'atr_period': 18,
                      'sl_pips': 0.3345,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.8892,
                      'tp_type': 'atr_mult',
                      'trail_atr_mult': 1.464,
                      'trail_type': 'atr_mult',
                      'trailing': True},
    'name': 'rsi_reversal_e47d038f'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_reversal_e47d038f"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
