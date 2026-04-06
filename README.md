# Polymarket Wallet Tracker Terminal

複数ウォレットのPolymarket取引を監視し、同一マーケットへの集中的な取引（クラスタ）をシグナルとして検知するCLIツール。シグナルに基づく自動売買（paper / dry-run / live）に対応。

## フォルダ構成

```
├── main.py                      # エントリーポイント
├── watchdog.py                  # main.py 自動再起動ラッパー
├── monitor.py                   # アラートチェック + 日次レポート保存
├── report.py                    # パフォーマンスレポートCLI
├── src/
│   ├── config.py                # 設定管理（.env + CSV読み込み）
│   ├── analytics.py             # 分析エンジン（edge/band/readiness）
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
│   ├── storage/                 # データ永続化
│   │   └── database.py          # SQLite（trades/signals/orders/fills/pnl）
│   ├── ui/                      # 表示
│   │   └── terminal.py          # Rich CLIターミナル
│   └── notifier/                # 通知
│       └── discord.py           # Discord Webhook
├── reports/                     # 日次レポート自動保存先
│   ├── report_2025-01-15.csv
│   └── report_2025-01-15.json
├── logs/                        # ログファイル自動生成
│   ├── watchdog_20250115.log
│   └── monitor_20250115.log
├── tests/                       # pytest テスト
├── .vscode/                     # VSCode設定（デバッグ・タスク）
├── wallets_seed.csv             # 監視ウォレット一覧（サンプル）
├── start.bat                    # Windows cmd 起動スクリプト
├── start.ps1                    # Windows PowerShell 起動スクリプト
├── run_all.bat                  # watchdog + monitor 同時起動
├── setup_tasks.ps1              # タスクスケジューラ登録
├── remove_tasks.ps1             # タスクスケジューラ削除
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

## 自動運用（完全放置モード）

PC起動後に自動でトラッカーを起動し、アラート・レポートを自動保存する仕組みです。

### 自動化の全体像

| タスク | トリガー | 動作 |
|--------|---------|------|
| **PolyTracker-Watchdog** | ログオン時 | `watchdog.py` を起動。main.py がクラッシュしたら自動再起動 |
| **PolyTracker-Monitor** | ログオン時 + 10分間隔 | `monitor.py` でアラートチェック + レポート保存 |
| **PolyTracker-DailyReport** | 毎日 21:00 | `report.py --v2-only --daily` でレポートを `reports/` に保存 |

### タスクスケジューラ登録手順（Windows）

**前提条件:**
- Python 3.11+ がインストール済み
- `venv` が作成済み（`python -m venv venv` → `pip install -r requirements.txt`）
- `.env` ファイルが設定済み

**手順:**

```powershell
# 1. PowerShell を「管理者として実行」で開く
# 2. プロジェクトディレクトリに移動
cd C:\my-ai-project

# 3. タスク登録
.\setup_tasks.ps1

# 4. 登録確認
Get-ScheduledTask -TaskName 'PolyTracker-*'

# 5. 詳細確認（最終実行時刻など）
Get-ScheduledTask -TaskName 'PolyTracker-*' | Get-ScheduledTaskInfo
```

### タスク削除

```powershell
# 全タスク一括削除
.\remove_tasks.ps1

# 個別削除
Unregister-ScheduledTask -TaskName 'PolyTracker-Watchdog' -Confirm:$false
Unregister-ScheduledTask -TaskName 'PolyTracker-Monitor' -Confirm:$false
Unregister-ScheduledTask -TaskName 'PolyTracker-DailyReport' -Confirm:$false
```

### 手動起動（1コマンド）

タスクスケジューラを使わず手動で全プロセスを起動する場合:

```cmd
run_all.bat
```

- Watchdog が新しいウィンドウで起動
- Monitor が同じウィンドウで10分間隔ループ開始
- 停止: 各ウィンドウで `Ctrl+C`

### Discord 通知（オプション）

`.env` に `DISCORD_WEBHOOK_URL` を設定すると、以下の場合に Discord 通知が送られます:

| アラート | 条件 | 色 |
|---------|------|-----|
| Edge Alert | edge <= 0（10トレード以上） | 赤 |
| PF Alert | Profit Factor < 1.0（10トレード以上） | オレンジ |
| Milestone | 100トレード到達 | 緑 |
| LIVE READY | 全条件クリア（n>=100, edge>0, PF>1, 複数市場） | 緑 |

**Discord 未設定でもクラッシュしません。** アラートはコンソールとログファイル（`logs/`）に出力されます。

### トラブルシューティング

| 症状 | 原因と対処 |
|------|-----------|
| タスクが実行されない | 管理者権限で `setup_tasks.ps1` を実行したか確認。`Get-ScheduledTask -TaskName 'PolyTracker-*'` で状態確認 |
| Python が見つからない | `venv\Scripts\python.exe` が存在するか確認。なければ `python -m venv venv` |
| DB が見つからない | `.env` の `DB_PATH` を確認。デフォルトは `tracker.db` |
| Discord 通知が来ない | `.env` の `DISCORD_WEBHOOK_URL` を確認。未設定ならログ出力のみ |
| ネット切断で停止した | Watchdog が最大2時間ネット復帰を待機。復帰後に自動再起動 |
| ログが見たい | `logs/watchdog_YYYYMMDD.log` / `logs/monitor_YYYYMMDD.log` を確認 |
| レポートが見たい | `reports/report_YYYY-MM-DD.csv` / `.json` を確認 |
| タスクを再登録したい | `.\remove_tasks.ps1` → `.\setup_tasks.ps1` |

### 放置運用チェックリスト

- [ ] `.env` が設定済み（`DATA_SOURCE`, `DB_PATH` 等）
- [ ] `venv` が作成済み + `requirements.txt` インストール済み
- [ ] `wallets_seed.csv` に監視ウォレットが登録済み
- [ ] `python main.py` で正常に起動することを確認
- [ ] `python monitor.py --check-only` でエラーが出ないことを確認
- [ ] `.\setup_tasks.ps1` を管理者権限で実行済み
- [ ] `Get-ScheduledTask -TaskName 'PolyTracker-*'` で3タスクが Ready 状態
- [ ] （任意）`DISCORD_WEBHOOK_URL` を設定してアラートをテスト
- [ ] PC再起動後に Watchdog が自動起動することを確認

全チェック完了で **放置OK** です。

## 今後の拡張ポイント

- **ポジション管理**: 保有ポジションの時価評価・自動利確/損切
- **バックテスト**: 過去データでシグナル精度と損益をシミュレーション
- **Web UI**: FastAPI + React でブラウザ管理
- **ウォレットスコアリング**: 的中率に基づく信頼度スコア
- **WebSocket**: ポーリングからリアルタイム購読へ
- **マルチチェーン**: Polygon以外のチェーンにも対応
- **ダッシュボード**: Grafana等でのビジュアル分析
