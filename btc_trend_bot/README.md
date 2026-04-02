# BTC Trend Long Bot

BTCUSDT専用の上昇トレンド特化型自動売買システム（Bitget対応）

## コンセプト

- **ロング専用**: 上昇トレンドで大きく取る設計
- **高TP重視**: トレンドフォロー型の利益最大化
- **ダマシ回避**: レンジ・下落相場でのエントリーを最小化
- **8戦略**: 基本4戦略 + 実データ向け厳格版4戦略
- **Bitget対応**: データ取得・ペーパートレード・将来のライブ運用

## 環境要件

- Python 3.11以上
- Windows / Linux / macOS

## セットアップ

```bash
cd btc_trend_bot
pip install -r requirements.txt
```

## クイックスタート

### 1. Bitgetからデータ取得

```bash
# 1時間足を取得 (2023年〜現在)
python -m btc_trend_bot.fetch_data --timeframe 1h --start 2023-01-01

# 全時間足を取得 (5m, 15m, 1h, 4h)
python -m btc_trend_bot.fetch_data --all-timeframes --start 2023-01-01

# 期間を指定
python -m btc_trend_bot.fetch_data --timeframe 1h --start 2023-01-01 --end 2024-12-31
```

### 2. 実データでバックテスト

```bash
# Bitgetから取得してそのままバックテスト（全戦略×全出口）
python -m btc_trend_bot.run_realdata_backtest --fetch --start 2023-01-01

# 既存CSVでバックテスト
python -m btc_trend_bot.run_realdata_backtest --data data/raw/BTCUSDT_1h.csv

# 特定戦略のみ
python -m btc_trend_bot.run_realdata_backtest --strategy pullback_strict --exit partial_trail

# 全戦略一括比較
python -m btc_trend_bot.run_realdata_backtest
```

### 3. ペーパートレード

```bash
# ヒストリカルシミュレーション（バックテスト的にペーパー実行）
python -m btc_trend_bot.run_paper --mode historical --data data/raw/BTCUSDT_1h.csv

# Bitgetからデータ取得してシミュレーション
python -m btc_trend_bot.run_paper --mode historical --fetch --start 2024-01-01

# ライブペーパートレード（Bitgetリアルタイムデータ、5分間隔）
python -m btc_trend_bot.run_paper --mode live --interval 300
```

### 4. 合成データでクイックテスト

```bash
# サンプルデータ生成 + 全戦略バックテスト
python -m btc_trend_bot.run_backtest --generate-data

# フルパイプライン
python -m btc_trend_bot.main --mode full
```

### 5. 最適化

```bash
python -m btc_trend_bot.run_optimize --trials 200
python -m btc_trend_bot.run_optimize --walk-forward --splits 5
python -m btc_trend_bot.run_optimize --strategy breakout_confirmed --trials 300
```

### 6. レポート出力

バックテスト実行時に自動生成：
- `reports/real_data/` - 実データレポート
- `reports/` - 合成データレポート

## プロジェクト構成

```
btc_trend_bot/
├── main.py                    # フルパイプライン
├── run_backtest.py            # バックテスト実行
├── run_realdata_backtest.py   # 実データバックテスト（Bitget対応）
├── run_optimize.py            # 最適化実行
├── run_paper.py               # ペーパートレード
├── fetch_data.py              # Bitgetデータ取得
├── data_loader.py             # データ読み込み・品質チェック
├── feature_engineering.py     # テクニカル指標一括追加
├── extract_bull_runs.py       # 上昇トレンド区間抽出
├── metrics.py                 # パフォーマンス指標計算
├── report_generator.py        # レポート・チャート出力
├── config/
│   └── settings.yaml          # 全設定（Bitget手数料含む）
├── exchange/                  # 取引所抽象化レイヤー
│   ├── base.py                # 取引所基底クラス
│   ├── models.py              # 注文・ポジションモデル
│   ├── bitget_public.py       # Bitget公開API（OHLCV取得）
│   └── bitget_private.py      # Bitget認証API（発注・残高）
├── indicators/
│   ├── trend.py               # 指標計算関数群
│   └── trend_detector.py      # トレンド判定クラス
├── strategies/
│   ├── base_strategy.py       # 戦略基底クラス
│   ├── trend_long/
│   │   ├── pullback_strategy.py         # 押し目買い
│   │   ├── breakout_strategy.py         # ブレイク継続
│   │   ├── reacceleration_strategy.py   # 再加速
│   │   ├── multi_tf_strategy.py         # マルチTF
│   │   ├── pullback_strict.py           # 押し目買い（厳格版）
│   │   ├── breakout_confirmed.py        # ブレイク確認済み
│   │   ├── reacceleration_quality.py    # 高品質再加速
│   │   └── multi_tf_trend_hold.py       # マルチTFトレンドホールド
│   └── filters/
│       └── trend_filter.py    # シグナルフィルタ群
├── backtest/
│   ├── engine.py              # バックテストエンジン
│   └── exit_manager.py        # 出口管理（6種類の利確 + 4種類のSL）
├── optimizer/
│   └── optimizer.py           # Optuna最適化 + ウォークフォワード
├── live/                      # ペーパー／ライブ取引
│   ├── paper_executor.py      # ペーパートレード実行器
│   ├── signal_engine.py       # シグナル生成エンジン
│   ├── position_manager.py    # ポジション管理
│   ├── risk_manager.py        # リスク管理
│   ├── bitget_feed.py         # Bitgetデータフィード
│   └── state_store.py         # 状態永続化
├── data/
│   ├── raw/                   # 生データCSV
│   └── processed/             # 加工済みデータ
├── reports/
│   └── real_data/             # 実データレポート
├── logs/
├── notebooks/
└── tests/
```

## 戦略一覧（8戦略）

### 基本戦略

| 戦略 | ロジック |
|------|---------|
| **Pullback** | RSI押し目 → 回復 + EMA50上 + 出来高確認 |
| **Breakout** | N期間高値更新 + 出来高増 + 収束後ブレイク |
| **Reacceleration** | BBスクイーズ解放 + ADX上昇 + レンジ上抜け |
| **Multi-TF** | 4H上昇トレンド + 15m精密エントリー |

### 厳格版（実データ最適化）

| 戦略 | 追加フィルタ |
|------|------------|
| **Pullback Strict** | 急騰後エントリー禁止 + trend_strength > 0.5 + VWAP上 |
| **Breakout Confirmed** | ADX + 出来高ダブル確認 + バー品質フィルタ + クールダウン |
| **Reacceleration Quality** | スクイーズ前のトレンド継続性評価 + 弱い抜け除外 |
| **MultiTF Trend Hold** | EMA完全整列 + 広めのSL + 長期保有設計 |

## 出口戦略（6種類）

1. **固定RR型**: 1:2, 1:3, 1:5
2. **ATRトレーリング**: ATR × 倍率のトレーリングストップ
3. **直近安値更新**: スイングロー割れまで保有
4. **EMA割れ**: EMA(20)を終値で割ったら撤退
5. **分割利確**: 50%を固定RRで利確 + 残りトレール
6. **出来高減衰**: 急騰後に出来高が減少したら手仕舞い

## Bitget設定

`config/settings.yaml` の `exchange` セクション:

```yaml
exchange:
  name: "bitget"
  maker_fee_pct: 0.02    # Bitget spot maker
  taker_fee_pct: 0.06    # Bitget spot taker
  slippage_bps: 5.0      # 5 basis points
  min_order_size_btc: 0.0001
  risk_per_trade_pct: 2.0
```

ライブ運用時はAPI情報を環境変数または`.env`で設定。

## 出力レポート

### 実データレポート (`reports/real_data/`)
- `実データ戦略ランキング.csv` - 全戦略ランキング
- `bull_only_ranking.csv` - Bull相場限定ランキング
- `regime_comparison.csv` - 相場局面別成績比較
- `strategy_vs_exit_matrix.csv` - 戦略×出口マトリクス
- `best_trade_examples_*.csv` - 最大利益トレード
- `worst_trade_examples_*.csv` - 最大損失トレード
- `best_strategy_realdata.md` - ベスト戦略詳細分析

### 共通レポート
- `{strategy}_equity.png` - エクイティカーブ
- `{strategy}_trades.csv` - トレード履歴
- `{strategy}_metrics.csv` - パフォーマンス指標

## 運用フロー

```
1. データ取得     → python -m btc_trend_bot.fetch_data
2. バックテスト   → python -m btc_trend_bot.run_realdata_backtest
3. 最適化         → python -m btc_trend_bot.run_optimize
4. ペーパー確認   → python -m btc_trend_bot.run_paper --mode historical
5. ペーパー運用   → python -m btc_trend_bot.run_paper --mode live
6. (将来) ライブ  → exchange/bitget_private.py + API設定
```
