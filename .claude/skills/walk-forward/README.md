# walk-forward skill

過学習を検出する2段目のskill。backtest skill が単一区間で検証するのに対し、
これは IS（最適化）→OOS（検証）を時間でローリングして汎化性能を測る。

## 構成
- `SKILL.md` — フロントマター付き仕様書（規約、判定ルール）
- `run_walk_forward.py` — ローリング実行＋集約＋過学習判定の標準ランナー
- `strategy_template.py` — `optimize` / `set_params` / `backtest` を備えたテンプレート

## 使い方
1. 戦略に `optimize(is_period, capital) -> dict` と `set_params(params)` を追加
2. ランナーを実行：

```bash
python .claude/skills/walk-forward/run_walk_forward.py \
  --strategy strategies/<name>.py \
  --symbol BTC/USDT --tf 1h \
  --period 2023-01-01:2025-01-01 \
  --is-months 12 --oos-months 3 --step-months 3
```

## 出力
`results/<name>_wf_<timestamp>/`
- `summary.json` — 全区間 + 結合 + 安定性 + 判定
- `per_window.csv` — 区間別 IS/OOS メトリクス
- `combined_equity.png` — OOS 結合エクイティカーブ
- `is_vs_oos.png` — IS PF / OOS PF の比較棒グラフ

## 終了コード
- `0`: 過学習判定をクリア
- `1`: 過学習で失格
- `2`: 引数・戦略ロードのエラー

## backtest skill との互換
同じ `Strategy` クラスで両方のskillに対応できる。`__init__` で `self.params = {}`
を持たせ、`backtest()` がそれを参照する形にしておけば、`set_params` を呼ばない
backtest skill 経由の実行でも従来どおり動作する。
