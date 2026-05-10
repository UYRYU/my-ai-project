---
name: backtest
description: 全Bot共通のバックテスト標準手順。新しい戦略は必ずこの手順で検証する。曖昧な検証を防ぎ、戦略間の正当な比較を可能にする。
---

# バックテスト標準手順

## いつ使うか
- 新しい戦略を実装したとき
- 既存戦略のパラメータを変更したとき
- 異なる戦略同士を比較するとき

## 戦略クラスの規約
全ての戦略ファイルは `Strategy` クラスを実装する：

```python
class Strategy:
    def __init__(self, symbol: str, tf: str, fee: float, slippage: float): ...
    def backtest(self, period: str, capital: float) -> tuple[list, list]:
        # Returns: (trades, equity)
        # trades: [{"entry_time","exit_time","side","entry_price","exit_price","pnl"}, ...]
        # equity: [初期資金, ..., 最終資金]
        ...
```

## 実行コマンド
```bash
python .claude/skills/backtest/run_backtest.py \
  --strategy strategies/<name>.py \
  --symbol BTC/USDT --tf 1h \
  --period 2023-01-01:2025-01-01 \
  --capital 10000 --fee 0.001 --slippage 0.0005
```

## 必須出力指標
| 指標 | 合格 | 警告 |
|---|---|---|
| 取引数 | 100以上 | 100未満は無効 |
| 勝率 | 40%以上 | - |
| PF | 1.3以上 | 3.0超は過学習を疑う |
| 最大DD | 30%以下 | - |
| シャープ | 1.0以上 | - |
| 期待値 | プラス | - |

## 必須出力ファイル
`results/<strategy>_<timestamp>/` 配下に：
- `metrics.json`
- `trades.csv`
- `equity_curve.png`

## 失格条件
- 取引数 < 100
- ルックアヘッドバイアス
- 単一パラメータでしか検証していない

## 過学習リスクのチェック
- PF > 3.0
- 勝率 > 70%
- パラメータ感度が高い
