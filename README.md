# my-ai-project / EMA10 × 15m トレード戦略 バックテスター

X(Twitter) で紹介されていた **「EMA10 × 15分足 × 8つのローソク足」** 手法
([元ツイート](https://x.com/cora64189920179/status/2039688312022024289))
を Python で再現し、ヒストリカルデータでバックテストするためのプロジェクト。

## 戦略ルール

### ロング
1. ローソク足の終値が EMA10 を **下→上** に抜けて足が確定 (ブレイク)
2. 終値が EMA10 の上を維持した状態でローソク足が EMA10 に **タッチ** (リテスト)
3. タッチ足が次のいずれかのパターン
   - **上昇ピンバー** (下ヒゲ ≥ 実体 × 2、上ヒゲ ≤ 実体)
   - **上昇継続足** (実体がレンジの 50% 以上の陽線)
4. 次の足の **始値でロングエントリー**
5. 利確 = 直近高値、 損切 = 直近安値

### ショート
ロングの反対 (EMA10 を上→下、下降ピンバー / 下降継続足、TP=直近安値、SL=直近高値)。

## 構成

```
trading/
├── __init__.py
├── strategy.py     # EMA, ローソク足パターン, シグナル生成
├── backtest.py     # トレード執行シミュレーション + 集計
└── data.py         # CSV / yfinance / 合成データのローダー
tests/
└── test_strategy.py
run_backtest.py     # CLI エントリポイント
requirements.txt
```

## セットアップ

```bash
pip install -r requirements.txt
```

`yfinance` がインストールできない環境では、CSV か合成データを使用してください。

## 実行方法

### 1. 合成データ (オフライン動作確認用)
```bash
python3 run_backtest.py --synthetic
```

### 2. 自前 CSV
1 列目を timestamp、列名 `open,high,low,close` の CSV を用意して:
```bash
python3 run_backtest.py --csv data/xauusd_15m.csv
```

### 3. yfinance (XAU/USD 代替: COMEX 金先物 GC=F)
```bash
python3 run_backtest.py --yfinance GC=F --period 60d --interval 15m
```
※ 15分足は yfinance の制約で過去 60 日程度しか取得できません。

### オプション
| フラグ | 説明 | デフォルト |
|---|---|---|
| `--ema N` | EMA 期間 | 10 |
| `--swing N` | 直近高値/安値の参照本数 | 20 |
| `--max-bars N` | 1 トレードの最大保有本数 | 500 |
| `--sl-mode {swing,atr}` | 損切モード | swing |
| `--tp-mode {swing,rr,atr}` | 利確モード | swing |
| `--rr R` | tp-mode=rr 時のリスクリワード比 | 2.0 |
| `--atr-period N` | ATR 期間 | 14 |
| `--atr-sl X` | ATR×X を SL 距離に使用 | 1.5 |
| `--atr-tp X` | ATR×X を TP 距離に使用 | 3.0 |
| `--trades-json PATH` | トレード明細を JSON 出力 | - |

## 出力例 (合成データ 4000本)

### デフォルト (swing TP / swing SL)
```
trades=153  win_rate=77.8%  total_r=+4.93  PF=1.14  max_dd=6.31R
```

### 最適化版 (ATR SL × RR TP)
```
$ python3 run_backtest.py --synthetic --sl-mode atr --tp-mode rr --rr 1.2 --atr-sl 1.0
trades=191  win_rate=59.7%  total_r=+59.80  PF=1.78  max_dd=8.20R
```

詳細は [TP/SL 最適化](#tpsl-最適化) を参照。

## TP/SL 最適化

`optimize.py` で TP/SL モードと係数の総当りグリッドサーチができます。

```bash
python3 optimize.py --synthetic --metric total_r --top 15
python3 optimize.py --synthetic --metric profit_factor
python3 optimize.py --synthetic --metric sharpe
```

検証範囲 (合計 88 通り):
- swing SL × swing TP (lookback ∈ {10,15,20,30,50})
- swing SL × RR TP (rr ∈ {0.5..3.0})
- ATR SL × RR TP (atr_sl ∈ {1.0..2.5}, rr ∈ {0.5..3.0})
- ATR SL × ATR TP (atr_sl ∈ {1.0..2.5}, atr_tp ∈ {1.0..4.0})

### 合成データでのトップ結果 (total_r 基準)

| # | SL | TP | params | trades | win% | avgR | totR | PF | DD |
|---|---|---|---|---|---|---|---|---|---|
| 1 | atr | rr | atr_sl=1.0, rr=2.5 | 166 | 39% | +0.36 | +60.1 | 1.59 | 9.50 |
| 2 | atr | rr | atr_sl=1.0, rr=1.2 | 191 | 60% | +0.31 | +59.8 | 1.78 | 8.20 |
| 3 | atr | atr | atr_sl=1.0, atr_tp=4.0 | 137 | 29% | +0.42 | +58.0 | 1.59 | 11.0 |

3 指標 (total_r / PF / sharpe) すべてで上位常連だったのは
**`--sl-mode atr --tp-mode rr --rr 1.2 --atr-sl 1.0`**。
元の swing/swing 設定に対して累計 R が +4.93 → +59.8 と **約 12 倍** に改善しました。

⚠️ これは合成データ上の最適化結果です。実データ (XAU/USD など) では分布が異なるため、
**実データで再度 `optimize.py` を回してから採用パラメータを決めてください**。
ウォークフォワード分析 (期間を分割して in-sample / out-of-sample 検証) も推奨です。

- `total_r` / `avg_r` … 1 トレードあたりリスク (|entry - stop|) を 1R とした倍率合計
- `max_dd_r` … エクイティカーブ (R ベース) の最大ドローダウン
- `profit_factor` … 総利益 ÷ 総損失

## テスト
```bash
python3 -m unittest tests.test_strategy -v
```

## 注意事項

- このリポジトリは **バックテスト / 学習用** であり、自動発注機能は含まれません。
- 実運用に向けては以下のような追加実装が必要です:
  - スプレッド / スリッページ / 手数料モデル
  - ロット計算 (リスク % ベース)
  - ブローカー API (OANDA, MT5 等) との接続
  - リアルタイム足確定検知とポジション管理
- 戦略のエッジは銘柄・期間によって大きく変動します。十分な期間 (数年) の実データで検証してから判断してください。
