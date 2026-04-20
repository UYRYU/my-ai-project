# polymarket-sports-arb

`sovereign2013` 風 Polymarket スポーツアービトラージボットの最小構成。

## アーキテクチャ

```
Gamma API ──▶ Market discovery (cheap, snapshot prices)
                │
                ├─▶ event_grouper  (slug 解析で同試合の市場を束ねる)
                │
                ├─▶ arbitrage.scan  (sum-of-asks < 1 候補抽出)
                │
                └─▶ orderbook.quote_basket_cost  (CLOB 実 depth で VWAP 検証)
                         │
                         ├─▶ risk.check  (ポジション/エクスポージャ上限)
                         └─▶ executor    (dry-run / live で発注)

Claude Opus 4.7 ─▶ claude_analyzer  (相関 basket 検出, prompt caching)
trade_log.jsonl ◀─ 全イベント append-only 記録
```

## ファイル

| 役割 | ファイル |
|---|---|
| 設定 | `src/config.py`, `.env.example` |
| 市場取得 | `src/polymarket.py` (Gamma + CLOB book) |
| 同試合グルーピング | `src/event_grouper.py` |
| アービ検出 | `src/arbitrage.py` (snapshot), `src/orderbook.py` (VWAP) |
| Claude 相関スカウト | `src/claude_analyzer.py` |
| ポジション・PnL | `src/positions.py` |
| リスク管理 | `src/risk.py` |
| 発注 | `src/executor.py` |
| ログ | `src/trade_log.py` → `trades.jsonl` |
| メインループ | `src/bot.py` |
| テスト | `tests/` (17 件) |

## セットアップ

```bash
pip install -r requirements.txt
cp .env.example .env
# .env を編集
python main.py
```

### オフラインで動作確認(API キー不要)

```bash
BOT_MOCK=true BOT_ONCE=true python main.py
```

期待出力:
```
[boot] dry_run=True mock=True once=True tags=('nba', 'nfl') ... claude=off
[tick 1] markets=3 events=1 candidates=1 pos=0 exposure=$0.00 pnl=$0.00
[DRY] same_market_sum_under_one edge=0.0500 — Will the Lakers beat the Celtics tonight?
  leg token=tok_lakers... price=0.4500
  leg token=tok_celtic... price=0.5000
```

`trades.jsonl` に boot/opportunity が JSONL で記録される。

### 本番ドライラン(ライブ市場、発注なし)

```bash
ANTHROPIC_API_KEY=sk-ant-... python main.py
# ANTHROPIC_API_KEY 未設定なら Claude スカウトはスキップされる
```

### ステップバイステップ(初回セットアップ)

1. **(漏洩キーがあれば revoke)** Polymarket → Settings → API Keys で古いキーを削除
2. **EOA 秘密鍵を取得**: Polymarket → Settings → Export Private Key
   - 画面/チャットには絶対に貼らない。`.env` に直接書く
3. **Funder アドレス確認**: Polymarket → Profile に表示されるプロキシウォレットアドレス
4. **`.env` 作成**:
   ```
   ANTHROPIC_API_KEY=sk-ant-...                  # 任意
   POLYMARKET_PRIVATE_KEY=0x<64桁>
   POLYMARKET_FUNDER_ADDRESS=0x<40桁>
   BOT_DRY_RUN=true
   ```
5. **ヘルスチェック**:
   ```bash
   python -m src.healthcheck
   ```
   全項目 ✓ になるまで進まない。USDC.e 残高が 0 なら Polymarket に deposit。
6. **オフラインスモークテスト**:
   ```bash
   BOT_MOCK=true BOT_ONCE=true python main.py
   ```
7. **ライブドライラン**(発注しない):
   ```bash
   python main.py
   ```
   `trades.jsonl` を眺めて検出機会の質と頻度を観察(数日推奨)
8. **ライブ少額**(怖い段階):
   - `BOT_MAX_POSITION_USD=5` に下げる
   - `BOT_DRY_RUN=false` に変更
   - 1 約定ごとに Polymarket UI で fill を目視確認

既定は `BOT_DRY_RUN=true`。実発注前に必ず:

1. ドライランで数日回して `trades.jsonl` を確認
2. 検出機会の質と頻度を見て `BOT_MIN_EDGE` を調整
3. `BOT_MAX_POSITION_USD` を最小にして `BOT_DRY_RUN=false`
4. 1 約定ごとに想定通りの fill か確認

## テスト

```bash
python -m pytest tests/ -v
```

## 設計判断

- **2段階スキャン**: Gamma snapshot は無料・速いが古い。CLOB book は本物だが遅い。 安い1段目で絞り、本気の機会だけ2段目で検証する。
- **Claude は間引き**: 相関検出は毎 tick ではなく 6 tick 毎(~1分)。市場 snapshot を prompt cache に置いて読みコストを 90% 削減。
- **Risk → Execute の分離**: `risk.check` はテスト可能、`executor` は副作用専用。
- **Dry-run でも positions.Book は更新**: ペーパートレード PnL を実時間で見られる。

## 実運用の現実

- 流動性のある試合は他ボットが秒以下で食う。**勝つにはレイテンシ**:
  - Gamma REST → CLOB WebSocket subscription に置換
  - Polygon RPC を専用ノード(Alchemy Growth 等)に
  - VPS を CLOB host と同 region に配置
- **手数料・ガスでアービ理論利益は半分以下になる** ことが多い
- **対戦相手は AI ではなくレイテンシが本番**: Claude は基本見送り、複雑な basket 判定だけに使う設計
- 規約・法域は自己責任(米国居住者は不可地域多数)

## 未実装(伸びしろ)

- CLOB WebSocket 直接購読
- 複数レッグ同時発注の atomic ロールバック
- Polygon オンチェーン状態からの起動時ポジション復元
- 解決時の自動 settle と realized PnL 計算
- Prometheus メトリクス出力
