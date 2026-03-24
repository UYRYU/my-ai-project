"""自動生成戦略: rsi_trend_9335db0f"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'max_atr': 0.77, 'min_atr': 0.0379, 'type': 'atr_filter'},
                         {'period': 106, 'type': 'htf_trend'},
                         {'end_hour': 18, 'start_hour': 9, 'type': 'time_filter'}],
    'entry_signal': {'period': 19, 'type': 'rsi_trend'},
    'exit_rules': {   'atr_period': 12,
                      'sl_atr_mult': 3.0281,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 2.7346,
                      'tp_pips': 0.5431,
                      'tp_type': 'fixed'},
    'name': 'rsi_trend_9335db0f'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "rsi_trend_9335db0f"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
