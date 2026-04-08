"""
strategy.py の単体テスト。
pandas だけで動くので `python -m unittest tests.test_strategy` で実行可。
"""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from trading.strategy import (
    bearish_entry_pattern,
    bullish_entry_pattern,
    ema,
    generate_signals,
    is_bearish_continuation,
    is_bearish_pinbar,
    is_bullish_continuation,
    is_bullish_pinbar,
)


class PatternTests(unittest.TestCase):
    def test_bullish_pinbar(self):
        # 下ヒゲ長い陽線
        self.assertTrue(is_bullish_pinbar(o=100, h=101, l=95, c=100.5))
        # 下ヒゲ無し → False
        self.assertFalse(is_bullish_pinbar(o=100, h=101, l=99.9, c=100.5))
        # 陰線 → False
        self.assertFalse(is_bullish_pinbar(o=100, h=101, l=95, c=99))

    def test_bearish_pinbar(self):
        self.assertTrue(is_bearish_pinbar(o=100, h=105, l=99.5, c=99.5))
        self.assertFalse(is_bearish_pinbar(o=100, h=100.1, l=99.5, c=99.5))

    def test_continuation(self):
        # 陽線: 実体 80% → 継続
        self.assertTrue(is_bullish_continuation(o=100, h=101.0, l=99.9, c=100.8))
        # 実体小さすぎ → False
        self.assertFalse(is_bullish_continuation(o=100, h=102, l=99, c=100.2))
        # 陰線版
        self.assertTrue(is_bearish_continuation(o=100, h=100.1, l=99.0, c=99.2))

    def test_entry_pattern_combos(self):
        # 継続陽線は bullish_entry_pattern も True
        self.assertTrue(bullish_entry_pattern(100, 101, 99.9, 100.8))
        # 下降継続は bearish_entry_pattern も True
        self.assertTrue(bearish_entry_pattern(100, 100.1, 99, 99.2))


class EMATests(unittest.TestCase):
    def test_ema_monotonic_input(self):
        s = pd.Series(np.arange(1, 21, dtype=float))
        e = ema(s, 10)
        # 初項は入力の初項と一致
        self.assertAlmostEqual(e.iloc[0], 1.0)
        # 増加列 → EMA も単調増加
        self.assertTrue((e.diff().dropna() > 0).all())


class SignalTests(unittest.TestCase):
    def test_no_signals_on_flat(self):
        # 完全フラットな価格では EMA ブレイクは起きないのでシグナル 0
        df = pd.DataFrame(
            {
                "open": [100.0] * 100,
                "high": [100.0] * 100,
                "low": [100.0] * 100,
                "close": [100.0] * 100,
            },
            index=pd.date_range("2024-01-01", periods=100, freq="15min"),
        )
        signals = generate_signals(df)
        self.assertEqual(signals, [])

    def test_signal_generation_runs_on_synthetic(self):
        from trading.data import synthetic_gold_15m
        df = synthetic_gold_15m(n_bars=500, seed=1)
        signals = generate_signals(df)
        # 生成ロジックが走り、少なくとも 1 つはシグナルが出るはず
        self.assertGreater(len(signals), 0)
        # エントリーは必ずタッチ足の次
        for s in signals:
            self.assertEqual(s.entry_index, s.index + 1)
            if s.side == "long":
                self.assertLess(s.stop, s.entry_price)
                self.assertGreater(s.take, s.entry_price)
            else:
                self.assertGreater(s.stop, s.entry_price)
                self.assertLess(s.take, s.entry_price)


if __name__ == "__main__":
    unittest.main()
