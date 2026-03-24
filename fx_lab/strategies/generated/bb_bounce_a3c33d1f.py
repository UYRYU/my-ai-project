"""自動生成戦略: bb_bounce_a3c33d1f"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [   {'period': 43, 'type': 'htf_trend'},
                         {'end_hour': 22, 'start_hour': 7, 'type': 'time_filter'}],
    'entry_signal': {'period': 10, 'std_mult': 2.1359, 'type': 'bb_bounce'},
    'exit_rules': {   'atr_period': 17,
                      'be_trigger_pips': 0.2642,
                      'breakeven': True,
                      'max_bars': 141,
                      'sl_atr_mult': 2.2068,
                      'sl_type': 'atr_mult',
                      'tp_atr_mult': 3.0936,
                      'tp_type': 'atr_mult'},
    'name': 'bb_bounce_a3c33d1f'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "bb_bounce_a3c33d1f"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
