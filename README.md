# Polymarket Wallet Tracker Terminal

複数ウォレットのPolymarket取引を監視し、同一マーケットへの集中的な取引（クラスタ）をシグナルとして検知するCLIツール。

## フォルダ構成

```
├── main.py                  # エントリーポイント
├── src/
│   ├── config.py            # 設定管理（.env + CSV読み込み）
│   ├── collector/           # データ取得層（差し替え可能）
│   │   ├── base.py          # 抽象インターフェース + Trade型
│   │   ├── mock.py          # モックデータ生成
│   │   └── polymarket.py    # Polymarket API接続
│   ├── processor/           # データ処理
│   │   ├── normalizer.py    # 正規化・重複除去
│   │   └── signal_detector.py  # クラスタ検知・スコアリング
│   ├── storage/             # データ永続化
│   │   └── database.py      # SQLite管理
│   ├── ui/                  # 表示
│   │   └── terminal.py      # Rich CLIターミナル
│   └── notifier/            # 通知
│       └── discord.py       # Discord Webhook
├── tests/                   # pytest テスト
├── wallets_seed.csv         # 監視ウォレット一覧（サンプル）
├── requirements.txt
├── .env.example
└── README.md
```

## セットアップ

### 1. Python環境の準備

Python 3.11以上が必要です。

```bash
# 仮想環境を作成（推奨）
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate
```

### 2. 依存パッケージのインストール

```bash
pip install -r requirements.txt
```

### 3. 設定ファイルの準備

```bash
cp .env.example .env
```

`.env` を編集して設定を調整してください。

### 4. ウォレットの登録

`wallets_seed.csv` を編集して、監視したいウォレットアドレスを追加してください。

```csv
address,label,note
0x1234...,Whale_A,大口トレーダー
```

## 実行

### モックモードで起動（デフォルト）

```bash
python main.py
```

### 本番モードで起動

`.env` で `DATA_SOURCE=polymarket` に変更してから実行。

### テスト実行

```bash
pytest tests/ -v
```

## MVPシグナル条件

以下の条件を**すべて**満たした場合にシグナルを発報します：

| 条件 | デフォルト値 |
|------|------------|
| 同一マーケット | 必須 |
| 時間窓 | 5分（300秒） |
| 最小ウォレット数 | 3 |
| 同方向の注文 | Buy-Yes / Buy-No / Sell-Yes / Sell-No |
| 強シグナル閾値 | 合計 $1,000 以上 |

すべて `.env` で変更可能です。

## Discord通知

`.env` に `DISCORD_WEBHOOK_URL` を設定するとシグナル検知時にDiscordへ通知されます。

## 今後の拡張ポイント

- **Web UI**: Rich CLI → FastAPI + React へ移行
- **リアルタイムWebSocket**: ポーリングからWebSocket購読へ
- **ウォレットスコアリング**: 過去の的中率に基づくウォレット信頼度
- **マルチチェーン対応**: Polygon以外のチェーンにも対応
- **アラート条件の高度化**: ポジションサイズの変化率、タイミングパターン
- **バックテスト機能**: 過去データでシグナル精度を検証
- **API化**: 他ツールから利用可能なREST API
- **ダッシュボード**: Grafana等でのビジュアル分析
