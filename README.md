# polymarket-sports-arb

Polymarket スポーツアービトラージボット。**現実的な運用**に振ってあります。

## 現実的な期待値(先に読む)

| 項目 | 現実 |
|---|---|
| 純アービ edge の分布 | 9割は 0.3% 未満。2% 超はほぼ無い |
| 競合 | 数十のボットが常時張っている。**REST ポーリングでは勝てない** |
| $50 ポジションでの1機会の利益 | 0.5% edge なら $0.25 |
| 必要な約定頻度 | 食うには 1日 100+ 約定 |
| これで $1 → $3.3M できるか? | ❌ できない(それには WS 直購読 + 近接配置 VPS + 専用 RPC が必要) |
| このコードで何ができるか | **機会の検出**・検証・記録・ドライラン。練習と観察用 |

**本気で稼ぎに行くなら**: このコードをベースに WebSocket 購読化・VPS を NY 配置・Polygon 専用ノードまで詰める必要があります。そこまで行って初めて $50 元手で年 $500〜$2,000 程度が見えてくる規模感。

## 2つの実行モード

| モード | 起動コマンド | 用途 |
|---|---|---|
| **REST ベース**(基礎) | `python main.py` | ローカル検証、設定調整、学習 |
| **WebSocket ベース**(本番) | `python -m src.ws_bot` | VPS 常駐、低レイテンシ、メトリクス出力 |

WS モードは `clob_ws.OrderbookCache` を使って CLOB の market channel を直接購読。REST ポーリング (~2s レイテンシ)と比べて ~50ms に短縮 → レース勝率が大きく改善。

## アーキテクチャ

```
[REST モード]
Gamma API ──▶ market_filter ──▶ arbitrage.scan ──▶ orderbook.depth検証 ──▶ risk.check ──▶ executor
                                                                                               │
                                                                              trades.jsonl ◀──┘

[WS モード]  ─── 本番運用向け ───
discovery_loop (Gamma 30s毎)              ws_supervisor                    trading_loop (100ms毎)
      │                                          │                                │
      │ markets/asset_ids                        │ CLOB market channel           │
      │                                          ▼                                │
      └──────────────▶ OrderbookCache ◀──────────┘                               │
                              │                                                   │
                              └───────────────────────────────────────────────────┘
                                                      │
                                                      ▼
                                  risk.check → executor → trades.jsonl
                                  metrics :9100/metrics (Prometheus)
```

**ホットループに Claude は入っていません**。レイテンシとコストでアービ edge が消えるので、Claude は日次レビュー専用(`python -m src.analyze`)。

## 使い方

### 1. オフラインでまず動作確認(鍵不要)

```bash
pip install -r requirements.txt
BOT_MOCK=true BOT_ONCE=true python main.py
```

期待出力:
```
[boot] dry_run=True mock=True once=True ... min_edge=0.003 max_pos=$50.0
[tick 1] raw=3 tradeable=3 candidates=1 pos=0 exposure=$0.00 pnl=$0.00 baskets_today=0
[DRY] basket cost ~$52.78
  leg token=tok_lakers... price=0.4500 size=55.5556
  leg token=tok_celtic... price=0.5000 size=50.0
```

### 2. 本番ドライラン(ライブ市場、発注なし)

```bash
cp .env.example .env
# .env 編集:
#   POLYMARKET_PRIVATE_KEY=0x<64桁> (Polymarket → Settings → Export Private Key)
#   POLYMARKET_FUNDER_ADDRESS=0x<40桁> (Profile に表示されるアドレス)
python -m src.healthcheck    # 全部 ✓ になるまで設定を直す
python main.py                # BOT_DRY_RUN=true 継続。数日回す
```

### 3. 日次レビュー

```bash
python -m src.analyze trades.jsonl
# ANTHROPIC_API_KEY を .env に入れてあれば Claude が健全性診断
```

### 4. ライブ少額(まだ早いけど形式上)

`.env` で `BOT_DRY_RUN=false` `BOT_MAX_POSITION_USD=5` に。1 約定ごとに Polymarket UI で fill を目視。

## ファイル

| 役割 | ファイル | テスト |
|---|---|---|
| 設定 | `src/config.py` | — |
| 市場取得 | `src/polymarket.py` | — |
| 市場品質フィルタ | `src/market_filter.py` | ✓ |
| 同試合グルーピング | `src/event_grouper.py` | ✓ |
| アービ検出(snapshot) | `src/arbitrage.py` | ✓ |
| Orderbook VWAP 検証 | `src/orderbook.py` | ✓ |
| ポジション・PnL | `src/positions.py` | ✓ |
| リスク管理(日次上限) | `src/risk.py` | ✓ |
| Atomic 発注 + unwind | `src/executor.py` | — (live 統合) |
| JSONL ログ | `src/trade_log.py` | — |
| メインループ | `src/bot.py` | — |
| ヘルスチェック | `src/healthcheck.py` | ✓ |
| Claude 日次レビュー | `src/analyze.py` | — |
| モックデータ | `src/mock_data.py` | — |

## リスク管理

現状のデフォルトで自動適用:

- 1 basket ポジション上限: `BOT_MAX_POSITION_USD` ($50)
- 総 gross exposure 上限: `10 × max_position` ($500)
- 1日の basket 上限: 200
- 1日の損失上限: $100(超えたら自動停止)
- Spread 上限: 5¢(これより広いマーケットはスキップ)
- マーケットの確率両端: 2〜98%(両端は直前噴き上げが多く誤検知)
- 試合終了までの時間: 15分〜72時間(両端は罠)
- Partial fill 時: 約定済みレグを best-bid 付近で自動 unwind(方向性エクスポージャを残さない)

設定を弄るなら `src/risk.py` と `src/market_filter.py` の kwargs。

## VPS デプロイ

本番稼働させるなら `deploy/README.md` に手順。要点:

```bash
# VPS (Ubuntu 22.04) で
git clone <your-fork> /opt/polymarket-bot
cd /opt/polymarket-bot
python3.11 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
cp .env.example .env && nano .env       # 秘密鍵はローカルで直書き
./.venv/bin/python -m src.healthcheck   # 全部 ✓ まで進まない
sudo cp deploy/polymarket-bot.service /etc/systemd/system/
sudo systemctl enable --now polymarket-bot
```

`curl http://localhost:9100/metrics` で Prometheus メトリクスが取れる。

## 未実装(次にやるべき残り)

1. **同試合クロスマーケット basket** — moneyline × spread × total で implied prob が矛盾する瞬間を捕捉(WS 購読が下地になる)
2. **Maker 注文に切り替え** — taker で cross-spread するとフィーで edge が消える
3. **Alchemy / Infura 専用 RPC** — `POLYGON_RPC` に設定(パブリック RPC は詰まる)
4. **自動 settle** — 市場解決時に payout を realized PnL に反映

## テスト

```bash
python -m pytest tests/ -v
```

38 件 pass。

## 重要な警告

- **他人にチャット/画面で秘密鍵や API キーを見せない**。貼った瞬間に漏洩扱い → 即 revoke
- Polymarket は米国居住者不可の地域多数。**自分の管轄を確認**
- これはツールで保証ではない。**自分が失える金額だけで動かす**
