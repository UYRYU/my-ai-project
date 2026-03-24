# Polymarket BTC Short-Term Arbitrage Bot (Paper Trading)

Polymarketの短期BTC市場を監視し、価格の歪み（mispricing）を検出してpaper trading（疑似売買）を行うbotです。

## 機能

- Polymarket CLOB APIからアクティブなBTC短期市場を自動検出
- WebSocketによるリアルタイム板情報の購読
- 5つのシグナル指標による歪み検出
  - **mispricing_score**: Yes/No ask合計の1.0からの乖離
  - **spread_score**: bid-askスプレッドの狭さ
  - **liquidity_score**: 板の厚さ
  - **momentum_filter**: 直近の価格変化率
  - **confidence_score**: 上記の重み付け合成スコア (0-100)
- Paper trading（疑似売買）によるエントリー/エグジット/PnL記録
- TP（利確）/SL（損切り）/タイムアウトによる自動エグジット
- 日次サマリーのJSON/CSV出力
- Discord webhook通知（オプション）

## 前提条件

- Python 3.11+
- pip

## セットアップ

```bash
# リポジトリのpolymarket_botディレクトリに移動
cd polymarket_bot

# 仮想環境を作成（推奨）
python -m venv venv

# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

# 依存関係をインストール
pip install -r requirements.txt

# 環境変数ファイルを作成
copy .env.example .env    # Windows
# cp .env.example .env    # macOS/Linux
```

## 設定

`.env` ファイルで設定を管理します。主要な設定項目：

| 変数名 | 説明 | デフォルト値 |
|--------|------|-------------|
| `POLYMARKET_API_BASE` | CLOB API URL | `https://clob.polymarket.com` |
| `POLL_INTERVAL_SEC` | 市場ポーリング間隔（秒） | `10` |
| `MISPRICING_THRESHOLD` | mispricing閾値 | `0.02` |
| `SPREAD_MAX` | 最大許容スプレッド | `0.10` |
| `LIQUIDITY_MIN_SIZE` | 最小板厚 | `50.0` |
| `CONFIDENCE_THRESHOLD` | シグナル発火閾値 | `60.0` |
| `PAPER_TRADE_SIZE` | 仮想取引サイズ | `10.0` |
| `PAPER_TAKE_PROFIT` | 利確幅 | `0.05` |
| `PAPER_STOP_LOSS` | 損切り幅 | `0.03` |
| `PAPER_TIMEOUT_SEC` | ポジションタイムアウト（秒） | `300` |
| `ENABLE_DISCORD` | Discord通知有効化 | `false` |

## 実行

```bash
# polymarket_botディレクトリから実行
cd polymarket_bot
python -m src.main
```

### 想定出力

```
2026-03-24 12:00:00 | INFO     | polymarket_bot | ==================================================
2026-03-24 12:00:00 | INFO     | polymarket_bot | Polymarket Arbitrage Bot starting (PAPER MODE)
2026-03-24 12:00:00 | INFO     | polymarket_bot | ==================================================
2026-03-24 12:00:01 | INFO     | polymarket_bot | Discovering BTC short-term markets...
2026-03-24 12:00:02 | INFO     | polymarket_bot | Found 3 BTC short-term markets
2026-03-24 12:00:02 | INFO     | polymarket_bot | Tracking 3 markets with 6 tokens
2026-03-24 12:00:03 | INFO     | polymarket_bot | Connecting to WebSocket: wss://ws-subscriptions-clob.polymarket.com/ws/market
2026-03-24 12:00:03 | INFO     | polymarket_bot | WebSocket connected

--------------------------------------------------
  SIGNAL DETECTED
--------------------------------------------------
  Time:          2026-03-24T12:01:15
  Market:        Will BTC be above $100k in 5 minutes?
  YES bid/ask:   0.48 / 0.49
  NO  bid/ask:   0.44 / 0.45
  Mispricing:    0.0600
  Confidence:    72.50
  Action:        BUY_NO
  Expected Edge: 0.0300
--------------------------------------------------

2026-03-24 12:01:15 | INFO     | polymarket_bot | PAPER ENTRY: id=a1b2c3d4 | BUY_NO | Will BTC be above $100k in 5 min @ 0.4500 | size=10.00
2026-03-24 12:03:20 | INFO     | polymarket_bot | PAPER EXIT: id=a1b2c3d4 | exit=0.4800 | pnl=0.3000 | hold=125s | CLOSED_TP
```

## テスト

```bash
cd polymarket_bot
python -m pytest tests/ -v
```

### テスト内容

- `test_models.py` - データモデルのテスト
- `test_signal_engine.py` - シグナルエンジンのテスト（mispricing, spread, liquidity, momentum, confidence）
- `test_paper_trader.py` - paper tradingのテスト（エントリー、TP/SL/タイムアウト、最大ポジション数）
- `test_metrics.py` - メトリクス集計のテスト

## ディレクトリ構成

```
polymarket_bot/
  README.md
  requirements.txt
  .env.example
  .env              # 自分で作成
  src/
    __init__.py
    main.py          # メインエントリーポイント
    config.py        # .env設定ローダー
    logger.py        # ロガー設定
    models.py        # データモデル（dataclass）
    market_discovery.py  # 市場検出・API通信
    websocket_client.py  # WebSocketクライアント
    signal_engine.py     # シグナル検出エンジン
    paper_trader.py      # paper trading エンジン
    metrics.py           # メトリクス集計・CSV/JSON出力
    notifier.py          # 通知（ターミナル + Discord）
  data/              # 日次サマリー・取引ログ出力先
  logs/              # アプリケーションログ
  tests/             # ユニットテスト
```

## 本番売買への拡張ポイント

### 1. Trader インターフェースの差し替え

`paper_trader.py` の `PaperTrader` クラスと同じインターフェースで `LiveTrader` を実装：

```python
class LiveTrader:
    def enter(self, signal: SignalResult) -> Optional[Position]: ...
    def check_exits(self, market: Market) -> list[Position]: ...
    def close_all(self, market: Market) -> list[Position]: ...
```

### 2. 認証の追加

Polymarket CLOB APIの認証（API Key, Secret, Passphrase）を `.env` に追加し、`httpx` のリクエストヘッダーに署名を含める。

### 3. オーダー実行

`py-clob-client` ライブラリを使用して実際の注文を送信：

```bash
pip install py-clob-client
```

### 4. リスク管理の強化

- 最大ポジションサイズの制限
- 1日の最大損失制限
- 同時ポジション数の制限（既に実装済み）
- スリッページ許容値の設定

### 5. 監視・アラート

- Grafana/Prometheus連携
- Slack通知の追加
- 異常検知（大量損失、API障害）

### 6. バックテスト

- 過去の板データを使用したバックテスト機能
- パラメータ最適化

## ライセンス

Private - 個人利用のみ
