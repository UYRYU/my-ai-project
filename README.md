# my-ai-project

ニュース駆動型の先物トレーディングEA。CNN / Reuters / BBC / Al Jazeera を継続監視し、Iran / Israel / US 戦況の「激化 / 沈静化」を Claude API で判定して、原油と日経225先物を自動売買する。

## 構成

```
News sources                Python service              MetaTrader 5
+--------------+   poll    +-----------------+  json  +---------------+
| CNN / RSS    | ────────▶ | news_monitor.py | ─────▶ | IranNewsEA.mq5|
+--------------+           |  Claude API     |        |  trail stop   |
                           +-----------------+        +---------------+
```

- **news_monitor.py** — `POLL_INTERVAL_SEC` 秒ごとに各ソースを取得し、新しい記事だけを Claude (`claude-opus-4-6` デフォルト) に渡してスタンスを判定。`signal_id` が変わるたびに `signals.json` を上書き。
- **IranNewsEA.mq5** — `signals.json` をタイマーでポーリング。新シグナルを検知すると反対玉をクローズ → 新規エントリー → 利が乗ったら `TrailStartPoints` から `TrailStepPoints` 幅でトレーリング。

## シグナルマッピング

| stance | crude_signal | nikkei_signal |
|--------|--------------|---------------|
| `escalation`    | BUY  | SELL |
| `de_escalation` | SELL | BUY  |
| `neutral`       | FLAT | FLAT |

`MIN_CONFIDENCE` (デフォルト 0.6) 未満は無視。MQL5 側の `MinConfidence` でさらに足切り可能。

## Python サービスのセットアップ

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python news_monitor.py
```

主な環境変数:

| 変数 | デフォルト | 説明 |
|------|-----------|------|
| `ANTHROPIC_API_KEY` | — | 必須 |
| `CLAUDE_MODEL` | `claude-opus-4-6` | コスト圧縮したい場合は `claude-haiku-4-5` などに変更可 |
| `POLL_INTERVAL_SEC` | `30` | ニュース取得間隔 |
| `SIGNAL_FILE` | `signals.json` | EA に渡すシグナルファイル (MT5 の `Common/Files` に置くと共有しやすい) |
| `MIN_CONFIDENCE` | `0.6` | この値未満のスタンスは無視 |

## MetaTrader 5 EA のセットアップ

1. `IranNewsEA.mq5` を `MQL5/Experts/` にコピーして MetaEditor でコンパイル。
2. Python が書き出す `signals.json` を MT5 が読める場所に置く:
   - 推奨: `<MT5データフォルダ>/MQL5/Files/Common/signals.json` (`FILE_COMMON` で読まれる)
   - もしくは `<MT5データフォルダ>/MQL5/Files/signals.json`
3. 任意のチャート (例: WTI または JP225) に EA をアタッチ。
4. 入力パラメータ:
   - `CrudeSymbol` / `NikkeiSymbol` — ブローカーの実際の銘柄名に合わせる
   - `CrudeLots` / `NikkeiLots` — 1 トレードあたりのロット
   - `InitialSLPoints` — 初期ストップロス (ポイント)
   - `TrailStartPoints` — トレーリング開始の利幅
   - `TrailStepPoints` — トレーリング時の SL 距離
   - `MinConfidence` — Claude 判定の信頼度しきい値
   - `MagicNumber` — 他 EA と衝突しないユニークな番号

## 注意 / Disclaimer

- これはテンプレ実装です。本番投入前に必ずデモ口座でバックテスト&フォワードテストすること。
- ニューススクレイピングはサイトの robots.txt と利用規約を遵守すること。CNN の記事 HTML は JS レンダリングのため取り損ねる場合あり — 必要なら有料 API (NewsAPI, Bloomberg 等) に差し替え。
- 自動売買にはスリッページ・ギャップリスク・誤シグナルリスクがあり、損失は自己責任。