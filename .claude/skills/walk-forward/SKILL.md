---
name: walk-forward
description: 過学習を検出するためのウォークフォワード検証。IS（最適化）→OOS（検証）を時間でローリングし、汎化性能を測る。backtest skillが「単一区間検証」なのに対し、これは「複数区間ローリング検証」。
---

# ウォークフォワード検証手順

## いつ使うか
- パラメータを最適化した戦略
- backtest skill で良好なメトリクスが出たが、過学習が疑われる戦略
- 本番投入前の最終チェック

## backtest skill との関係
- backtest skill は **単一区間** で検証する
- walk-forward skill は **IS（最適化期間）→OOS（検証期間）** を時間でローリングし、複数区間で検証する
- backtest を通った後にこれを通すのが標準フロー

## 戦略クラスの追加規約
backtest skill の `Strategy` 規約に加えて、以下を実装する：

```python
class Strategy:
    def __init__(self, symbol: str, tf: str, fee: float, slippage: float): ...

    def optimize(self, is_period: str, capital: float) -> dict:
        # IS区間で最適パラメータを探索して返す
        ...

    def set_params(self, params: dict) -> None:
        # OOS実行前にパラメータを設定
        ...

    def backtest(self, period: str, capital: float) -> tuple[list, list]:
        # backtest skill と同じシグネチャ
        # set_params で設定された self.params を参照する
        ...
```

ランナーは各区間で次の順に呼ぶ：
1. `params = strategy.optimize(is_period, capital)`
2. `strategy.set_params(params)`
3. `is_trades, is_equity  = strategy.backtest(is_period, capital)`
4. `oos_trades, oos_equity = strategy.backtest(oos_period, capital)`

## 区間分割ルール
- IS: 12ヶ月、OOS: 3ヶ月、ステップ: 3ヶ月（デフォルト）
- CLI引数 `--is-months / --oos-months / --step-months` で変更可能
- 全期間 = IS + OOS×N回 が成立する範囲で window を生成
- `oos_end > 全期間end` になった時点で打ち切り

例：`2023-01-01:2025-01-01`、IS=12, OOS=3, step=3 → 4区間
- W1: IS 2023-01〜2024-01 / OOS 2024-01〜2024-04
- W2: IS 2023-04〜2024-04 / OOS 2024-04〜2024-07
- W3: IS 2023-07〜2024-07 / OOS 2024-07〜2024-10
- W4: IS 2023-10〜2024-10 / OOS 2024-10〜2025-01

## 実行コマンド
```bash
python .claude/skills/walk-forward/run_walk_forward.py \
  --strategy strategies/<name>.py \
  --symbol BTC/USDT --tf 1h \
  --period 2023-01-01:2025-01-01 \
  --is-months 12 --oos-months 3 --step-months 3 \
  --capital 10000 --fee 0.001 --slippage 0.0005
```

## 必須出力指標

### 区間別
- IS PF / OOS PF
- IS Sharpe / OOS Sharpe
- IS 勝率 / OOS 勝率
- IS 取引数 / OOS 取引数

### 全OOS結合
全区間のOOSトレードを時系列で連結して計算：
- PF, 勝率, MaxDD, シャープ, 期待値, 総リターン

### 安定性
- mean(IS PF), mean(OOS PF)
- OOS PF の標準偏差
- IS-OOS 劣化率 = (mean(IS PF) − mean(OOS PF)) / mean(IS PF)

## 過学習判定ルール
以下のいずれかに該当 → **OVERFIT**（終了コード 1）：
- mean(IS PF) / mean(OOS PF) > 2.0
- OOS PF が 1.0 を下回る区間が **半数以上**

警告（fail にはしない）：
- OOS PF の標準偏差が大きい → 不安定

## 必須出力ファイル
`results/<strategy>_wf_<timestamp>/` 配下に：
- `summary.json` — 全区間メトリクス + 結合 + 安定性 + 判定
- `per_window.csv` — 区間別 IS/OOS メトリクス
- `combined_equity.png` — OOS 結合エクイティカーブ
- `is_vs_oos.png` — IS PF / OOS PF の棒グラフ比較

## 終了コード
- `0`: 過学習判定をクリア
- `1`: 過学習判定で失格
- `2`: 引数・戦略ロードのエラー
