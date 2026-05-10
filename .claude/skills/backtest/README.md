# backtest skill

全Bot共通のバックテスト標準手順。

## 構成
- `SKILL.md` — Agent Skills のフロントマター付き仕様書（合格/失格/警告基準を含む）
- `run_backtest.py` — 戦略を動的ロードして指標を計算する標準ランナー
- `strategy_template.py` — 新しい戦略を書くときのテンプレート

## 使い方

1. `strategies/<name>.py` を作る（`strategy_template.py` をコピー）
2. `Strategy` クラスを実装する
3. ランナーを実行：

```bash
python .claude/skills/backtest/run_backtest.py \
  --strategy strategies/<name>.py \
  --symbol BTC/USDT --tf 1h \
  --period 2023-01-01:2025-01-01 \
  --capital 10000 --fee 0.001 --slippage 0.0005
```

## 出力
`results/<name>_<timestamp>/`
- `metrics.json` — 全指標と合格判定
- `trades.csv` — トレード明細
- `equity_curve.png` — エクイティカーブ（matplotlib があれば）

## 終了コード
- `0`: 全合格
- `1`: いずれかの合格基準を満たさない
- `2`: 戦略ファイルが見つからない等の引数エラー

## 依存
- 必須: Python 3.10+
- 任意: `matplotlib`（無ければ画像出力をスキップ）
