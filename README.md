# Polymarket Wallet Tracker Terminal

複数ウォレットのPolymarket取引を監視し、同一マーケットへの集中的な取引（クラスタ）をシグナルとして検知するCLIツール。シグナルに基づく自動売買（paper / dry-run / live）に対応。

## フォルダ構成

```
├── main.py                      # エントリーポイント
├── src/
│   ├── config.py                # 設定管理（.env + CSV読み込み）
│   ├── collector/               # データ取得層（差し替え可能）
│   │   ├── base.py              # 抽象インターフェース + Trade型
│   │   ├── mock.py              # モックデータ生成
│   │   └── polymarket.py        # Polymarket API接続
│   ├── processor/               # データ処理
│   │   ├── normalizer.py        # 正規化・重複除去
│   │   └── signal_detector.py   # クラスタ検知・スコアリング
│   ├── execution/               # 自動売買レイヤー
│   │   ├── models.py            # Order / Fill / PnL データモデル
│   │   ├── executor.py          # シグナル→発注のオーケストレーター
│   │   ├── risk_manager.py      # リスク管理（上限・kill switch）
│   │   ├── paper_broker.py      # 仮想約定（v2_binary / v1_random 切替可）
│   │   ├── csv_writer.py        # Paper取引CSV出力
│   │   └── live_broker.py       # 実注文（Liveモード / CLOB API）
│   ├── analytics.py             # 分析エンジン（市場別・時間帯別・DD等）
│   ├── storage/                 # データ永続化
│   │   └── database.py          # SQLite（trades/signals/orders/fills/pnl）
│   ├── ui/                      # 表示
│   │   └── terminal.py          # Rich CLIターミナル
│   └── notifier/                # 通知
│       └── discord.py           # Discord Webhook
├── report.py                    # パフォーマンスレポートCLI
├── tests/                       # pytest テスト（49件）
├── .vscode/                     # VSCode設定（デバッグ・タスク）
├── wallets_seed.csv             # 監視ウォレット一覧（サンプル）
├── start.bat                    # Windows cmd 起動スクリプト
├── start.ps1                    # Windows PowerShell 起動スクリプト
├── requirements.txt
├── pyproject.toml
├── .env.example
└── README.md
```

## セットアップ

### Windows（VSCode推奨）

```powershell
git clone <repository-url>
cd my-ai-project
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python main.py
```

またはダブルクリック: `start.bat`

### macOS / Linux

```bash
git clone <repository-url>
cd my-ai-project
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py
```

## 取引モード

3つのモードを `.env` の `TRADING_MODE` で切り替え可能:

| モード | 動作 | 用途 |
|--------|------|------|
| `paper` | 仮想約定（デフォルト） | 戦略検証・動作確認 |
| `dry-run` | 注文内容を表示するだけ | 本番前の最終確認 |
| `live` | 実注文を送信 | 本番運用 |

### Paper モードで検証する手順

1. `.env` で `TRADING_MODE=paper`（デフォルト）
2. `python main.py` で起動
3. シグナル検知時に仮想約定が行われる
4. `Execution Status` パネルで注文数・約定数・損益を確認
5. SQLite `tracker.db` の `orders` / `fills` テーブルで履歴確認
6. `python report.py` で詳細レポートを表示
7. `python report.py --equity-csv` でエクイティカーブをCSV出力

### Paper モデル（v2: Binary Outcome Model）

デフォルトの仮想決済モデルは **v2_binary**（二値収束モデル）です。

Polymarketは二値オプション（最終的に $1.00 か $0.00 に解決）です。
v2モデルはこの特性を忠実に再現します:

| Side | 勝ち条件 | exit | 負け条件 | exit |
|------|---------|------|---------|------|
| **Buy** | 確率 = entry_price で的中 | 0.99 | 確率 = 1-entry_price で外れ | 0.01 |
| **Sell** | 確率 = 1-entry_price で的中 | 0.01 | 確率 = entry_price で外れ | 0.99 |

**損益計算:**
- Buy: `PnL = (exit - entry) * shares` （`shares = amount / entry`）
- Sell: `PnL = (entry - exit) * shares`

**特徴:**
- entry_price = 市場推定の勝率。安い(0.20)なら勝率20%だが1勝の利益が大きい
- 効率的市場の仮定では期待PnL ≈ 0。シグナルが正しければプラスに偏る
- 旧v1モデル（ランダム±15%）と異なり、Polymarketの本質を反映

**旧モデルに切り替え:**
```
LEGACY_PAPER_MODEL=true
```

v1(random) と v2(binary) の取引は `model_version` 列で区別され、レポートにも表示されます。

### Live モードへの移行手順

**段階的に進めること。いきなり live にしない。**

1. **paper で十分に検証** → 約定ログと損益を確認
2. **dry-run で確認** → `.env` で `TRADING_MODE=dry-run` に変更、注文内容が正しいか確認
3. **Live の認証情報を設定**:
   ```
   POLY_PRIVATE_KEY=0x...
   POLY_API_KEY=...
   POLY_API_SECRET=...
   POLY_API_PASSPHRASE=...
   ```
4. **py-clob-client をインストール**: `pip install py-clob-client`
5. **安全装置を確認**: `MAX_ORDER_USD=50`, `MAX_DAILY_LOSS_USD=100`
6. **TRADING_MODE=live に変更**
7. **ALLOW_LIVE_TRADING=true に変更**（二重安全装置）
8. 起動して動作を監視

## リスク管理

| 設定項目 | デフォルト | 説明 |
|---------|-----------|------|
| `MAX_ORDER_USD` | 50 | 1回あたりの最大注文額 |
| `MAX_POSITION_USD` | 200 | マーケットごとの最大ポジション |
| `MAX_DAILY_LOSS_USD` | 100 | 日次損失上限（到達で自動停止） |
| `MIN_SIGNAL_LEVEL` | STRONG | 発注対象のシグナルレベル |
| `ORDER_COOLDOWN_SEC` | 300 | 同一マーケットへの連続発注制限 |
| `ALLOW_LIVE_TRADING` | false | Live取引の二重安全装置 |
| `KILL_SWITCH` | false | 緊急停止フラグ |
| `LEGACY_PAPER_MODEL` | false | true でv1(random)モデルに切替 |

### 緊急停止（Kill Switch）

以下のいずれかで全注文を即座に停止:

1. `.env` で `KILL_SWITCH=true` に変更
2. プロジェクトルートに `KILL_SWITCH` ファイルを作成: `echo. > KILL_SWITCH`
3. 環境変数 `KILL_SWITCH=true` を設定

## Live モードに必要な認証情報

| 項目 | 取得方法 |
|------|---------|
| `POLY_PRIVATE_KEY` | Polygonウォレットの秘密鍵 |
| `POLY_API_KEY` | Polymarket CLOB API Key |
| `POLY_API_SECRET` | Polymarket CLOB API Secret |
| `POLY_API_PASSPHRASE` | Polymarket CLOB API Passphrase |

**注意**: Paper/dry-run モードでは認証情報は不要です。

## テスト実行

```bash
python -m pytest tests/ -v
```

## 今後の拡張ポイント

- **ポジション管理**: 保有ポジションの時価評価・自動利確/損切
- **バックテスト**: 過去データでシグナル精度と損益をシミュレーション
- **Web UI**: FastAPI + React でブラウザ管理
- **ウォレットスコアリング**: 的中率に基づく信頼度スコア
- **WebSocket**: ポーリングからリアルタイム購読へ
- **マルチチェーン**: Polygon以外のチェーンにも対応
- **ダッシュボード**: Grafana等でのビジュアル分析
