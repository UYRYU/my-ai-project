# polymarket-sports-arb

`sovereign2013` 風の Polymarket スポーツアービトラージボットの最小構成。

## やっていること

1. Gamma API で NBA / NFL / CBB / CFB 等のアクティブ市場を取得
2. **同一市場内アービ**: 全アウトカム ask の合計が 1.0 未満 → 全買いで無リスク利益
3. **Claude Opus 4.7** で相関市場(同試合の別リスティング、スプレッド/トータル等)の basket を検出
4. 見つかった機会をドライラン表示 / 実発注(live モード時)

## セットアップ

```bash
pip install -r requirements.txt
cp .env.example .env
# .env を編集: ANTHROPIC_API_KEY は必須。実発注するなら POLYMARKET_PRIVATE_KEY と FUNDER も
python main.py
```

既定は `BOT_DRY_RUN=true` — 実発注はしません。`false` に変更する前に必ず小額で検証してください。

## ファイル構成

- `src/polymarket.py` — Gamma / CLOB API 薄ラッパ
- `src/arbitrage.py` — 算術アービ(sum-of-asks < 1)
- `src/claude_analyzer.py` — Claude で cross-market 相関検出(system/market snapshot は prompt caching 済み)
- `src/executor.py` — 発注(デフォルト dry-run)
- `src/bot.py` — メインループ

## 現実的な注意

- Polymarket の流動性の深い試合はほぼ全てボットが張っており、純粋な sum-under-one は一瞬で消える
- 勝ち筋は **レイテンシ**(WebSocket 直接接続 + Polygon RPC 近接化) と **相関検出の質**
- 手数料・ガス・スリッページで理論利益は薄くなる
- 規約・法域を自分の責任で確認すること(米国居住者は利用不可の地域多数)

## 次にやると良いこと

- Gamma REST ポーリングを CLOB WebSocket サブスクリプションに置き換え(レイテンシ改善)
- 複数レッグの同時発注失敗時のロールバック
- ポジション管理 / 実現 PnL トラッキング
- Claude の `extended thinking` を複雑な basket 判定に限定してコスト抑制
