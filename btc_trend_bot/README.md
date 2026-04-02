# BTC Trend Long Bot

BTCUSDT専用の上昇トレンド特化型自動売買システム（バックテスト・最適化環境）

## コンセプト

- **ロング専用**: ショートは行わない。上昇トレンドで大きく取る設計
- **高TP重視**: スキャルではなく、トレンドフォロー型の利益最大化
- **ダマシ回避**: レンジ・下落相場でのエントリーを最小化
- **複数戦略**: 押し目買い、ブレイク継続、再加速、マルチタイムフレーム

## 環境要件

- Python 3.11以上
- Windows / Linux / macOS

## セットアップ

```bash
cd btc_trend_bot
pip install -r requirements.txt
```

## クイックスタート

### 1. サンプルデータ生成 + フルパイプライン実行

```bash
python -m btc_trend_bot.main --mode full
```

これで以下が自動実行されます：
1. サンプルデータ生成（3年分の合成BTCUSDT 1hデータ）
2. テクニカル指標計算
3. 上昇トレンド区間抽出
4. 全戦略バックテスト
5. パラメータ最適化
6. レポート生成

### 2. バックテストのみ

```bash
# 全戦略
python -m btc_trend_bot.run_backtest --generate-data

# 特定戦略
python -m btc_trend_bot.run_backtest --strategy pullback --exit atr_trailing

# 上昇相場のみでテスト
python -m btc_trend_bot.run_backtest --bull-only
```

### 3. 最適化のみ

```bash
# 標準最適化
python -m btc_trend_bot.run_optimize --trials 200

# ウォークフォワード最適化
python -m btc_trend_bot.run_optimize --walk-forward --splits 5

# 特定戦略の最適化
python -m btc_trend_bot.run_optimize --strategy breakout --trials 300
```

### 4. 上昇トレンド区間抽出

```bash
python -m btc_trend_bot.extract_bull_runs
```

### 5. 実データの使い方

`data/raw/` に以下の形式のCSVを配置：

```
datetime,open,high,low,close,volume
2021-01-01 00:00:00,29000.0,29100.0,28900.0,29050.0,1234.5
...
```

ファイル名例: `BTCUSDT_1h.csv`, `BTCUSDT_15m.csv`

## プロジェクト構成

```
btc_trend_bot/
├── main.py                  # フルパイプライン実行
├── run_backtest.py          # バックテスト実行
├── run_optimize.py          # 最適化実行
├── data_loader.py           # データ読み込み・品質チェック
├── feature_engineering.py   # テクニカル指標一括追加
├── extract_bull_runs.py     # 上昇トレンド区間抽出
├── metrics.py               # パフォーマンス指標計算
├── report_generator.py      # レポート・チャート出力
├── config/
│   └── settings.yaml        # 全設定ファイル
├── indicators/
│   ├── trend.py             # 指標計算関数群
│   └── trend_detector.py    # トレンド判定クラス
├── strategies/
│   ├── base_strategy.py     # 戦略基底クラス
│   ├── trend_long/
│   │   ├── pullback_strategy.py       # A. 押し目買い
│   │   ├── breakout_strategy.py       # B. ブレイク継続
│   │   ├── reacceleration_strategy.py # C. 再加速
│   │   └── multi_tf_strategy.py       # D. マルチTF
│   └── filters/
│       └── trend_filter.py  # シグナルフィルタ群
├── backtest/
│   ├── engine.py            # バックテストエンジン
│   └── exit_manager.py      # 出口管理（6種類の利確 + 4種類のSL）
├── optimizer/
│   └── optimizer.py         # Optuna最適化 + ウォークフォワード
├── live/                    # ライブ取引用（将来拡張）
├── data/
│   ├── raw/                 # 生データCSV
│   └── processed/           # 加工済みデータ
├── reports/                 # 出力レポート
├── logs/                    # ログファイル
├── notebooks/               # 分析用ノートブック
└── tests/                   # テスト
```

## 戦略一覧

### A. 押し目買い (Pullback)
上位足で上昇トレンド確認後、RSIが一時的に低下して回復するタイミングでエントリー。
EMA50上・出来高確認付き。

### B. ブレイク継続 (Breakout)
直近N期間の高値を出来高増加を伴って突破した場合にエントリー。
事前の収束期間とダマシフィルタ付き。

### C. 再加速 (Reacceleration)
BBがKC内に入るスクイーズ後の解放を狙う。
ADX上昇 + レンジ上抜けで再加速の初動を捕捉。

### D. マルチタイムフレーム (Multi-TF)
4H足で上昇トレンド確認 → 15m足で精密エントリー。
上位足と逆行するエントリーは禁止。

## 出口戦略（6種類の利確方式を比較可能）

1. **固定RR型**: 1:2, 1:3, 1:5
2. **ATRトレーリング**: ATR × 倍率のトレーリングストップ
3. **直近安値更新**: スイングロー割れまで保有
4. **EMA割れ**: EMA(20)を終値で割ったら撤退
5. **分割利確**: 50%を固定RRで利確 + 残りトレール
6. **出来高減衰**: 急騰後に出来高が減少したら手仕舞い

## 評価指標

- 総利益 / Profit Factor / Expectancy
- 最大ドローダウン / Calmar Ratio
- 勝率 / 平均利益÷平均損失
- 高TP達成率 (RR > 3.0)
- 相場局面別成績 (Bull / Bear / Sideways)
- 最大利益トレードTop10分析
- 最大損失トレードTop10分析

## 出力レポート

`reports/` ディレクトリに自動保存：
- `strategy_ranking.csv` - 戦略別ランキング
- `{strategy}_equity.png` - エクイティカーブ
- `{strategy}_trades.csv` - トレード履歴
- `{strategy}_metrics.csv` - パフォーマンス指標
- `{strategy}_bull_only_metrics.csv` - Bull相場限定成績
- `optimization_ranking.csv` - 最適化ランキング
- `best_parameters.csv` - 最適パラメータ
- `ベスト戦略要約.md` - ベスト戦略の詳細分析

## 設定変更

`config/settings.yaml` で全パラメータを調整可能：
- 初期資金、手数料、スリッページ
- トレンド判定パラメータ
- 各戦略のパラメータ
- 出口条件の設定
- 最適化の試行回数・分割比率

## 将来の拡張

- `live/` ディレクトリにBybit/Binance接続モジュールを追加予定
- ccxtライブラリで取引所API接続
- リアルタイムデータフィード
- ショート戦略の追加（BaseStrategyを継承して拡張可能）
