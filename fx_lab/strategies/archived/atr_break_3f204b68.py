"""自動生成戦略: atr_break_3f204b68"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engine.configurable_strategy import ConfigurableStrategy

CONFIG = {   'entry_filters': [{'period': 46, 'type': 'htf_trend'}],
    'entry_signal': {'multiplier': 1.5282, 'period': 25, 'type': 'atr_break'},
    'exit_rules': {   'atr_period': 13,
                      'be_trigger_pips': 0.1804,
                      'breakeven': 1,
                      'sl_atr_mult': 1.5324,
                      'sl_pips': 0.3804,
                      'sl_type': 'fixed',
                      'tp_atr_mult': 2.7237,
                      'tp_type': 'atr_mult',
                      'trail_atr_mult': 1.6748,
                      'trail_distance': 0.3584,
                      'trail_type': 'atr_mult',
                      'trailing': True},
    'name': 'atr_break_3f204b68'}

class GeneratedStrategy(ConfigurableStrategy):
    name = "atr_break_3f204b68"

    def __init__(self, spread: float = 0.2, commission: float = 0.01):
        super().__init__(config=CONFIG, spread=spread, commission=commission)
