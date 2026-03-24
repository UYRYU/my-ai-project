# AI News Automation

海外AI情報ソースを定期監視し、記事を日本語で要約・構造化して
**X投稿案**と**note下書き**を自動生成する Python 自動化ツール。

---

## 概要

```
監視ソース取得
  → 本文抽出
  → 日本語要約（Claude API）
  → 構造化（思想・実装・示唆）
  → 類似度チェック（重複排除）
  → X投稿案3件生成
  → note下書きMarkdown生成
  → 承認キューに保存
  → 人間がレビュー → 承認/却下
  → 承認済みをファイル出力
```

**完全自動投稿はしない**設計です。X・noteへの実際の投稿は人間が行います。

---

## ディレクトリ構成

```
my-ai-project/
├── README.md
├── requirements.txt
├── .env.example              # 環境変数テンプレート
├── sources.yaml              # 監視対象ソース定義
├── config/
│   └── settings.yaml         # 閾値・出力数などの設定
├── data/
│   ├── raw/                  # 取得した生記事JSON
│   ├── processed/            # 要約・構造化済みJSON
│   ├── drafts/
│   │   ├── x_posts/          # 出力済みX投稿案（.txt）
│   │   └── notes/            # 出力済みnote下書き（.md）
│   ├── logs/                 # 日付別ログ（YYYYMMDD.log）
│   └── state/
│       ├── approval_queue.json   # 承認キュー
│       └── processed_summaries.json  # 重複チェック用テキスト
├── src/
│   ├── main.py               # エントリポイント
│   ├── models.py             # 共通データモデル（dataclass）
│   ├── fetch/
│   │   ├── fetch_sources.py  # ソース取得・ディスパッチ
│   │   └── parse_article.py  # 記事の正規化・本文抽出
│   ├── process/
│   │   ├── summarize.py      # 日本語要約（Claude API / ダミー）
│   │   ├── structure.py      # 思想・実装・示唆への再構造化
│   │   └── dedupe.py         # 類似度チェック・重複排除
│   ├── generate/
│   │   ├── x_writer.py       # X投稿案生成（3件）
│   │   └── note_writer.py    # note下書きMarkdown生成
│   ├── review/
│   │   └── approval_queue.py # 承認キュー管理・CLIレビュー
│   ├── publish/
│   │   ├── export_x_posts.py # 承認済みX投稿案をtxtに出力
│   │   └── export_note_md.py # 承認済みnote下書きをmdに出力
│   └── utils/
│       ├── logger.py         # ログ設定（ファイル＋コンソール）
│       ├── fileio.py         # YAML/JSON/テキストIO
│       └── similarity.py     # コサイン類似度・Jaccard類似度
└── prompts/
    ├── summarize_prompt.md   # 要約プロンプト
    ├── structure_prompt.md   # 構造化プロンプト
    ├── x_post_prompt.md      # X投稿案生成プロンプト
    └── note_prompt.md        # note下書き生成プロンプト
```

---

## セットアップ

### 1. 前提

- Python 3.11 以上
- pip

### 2. 依存パッケージのインストール

```bash
pip install -r requirements.txt
```

### 3. 環境変数の設定

```bash
cp .env.example .env
```

`.env` を編集して `ANTHROPIC_API_KEY` を設定してください。

```
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxx
```

> **APIキーなしでも動作します。** その場合はテンプレートベースのダミーデータが生成されます。

### 4. 監視ソースの設定

`sources.yaml` を編集して監視対象を登録します。

```yaml
sources:
  - name: "OpenAI Blog"
    platform: "web"
    handle_or_url: "https://openai.com/blog"
    enabled: true
    priority: 1
```

### 5. 設定の調整（任意）

`config/settings.yaml` で以下を変更できます：

| 設定キー | デフォルト | 説明 |
|---|---|---|
| `similarity.threshold` | `0.75` | 重複判定の類似度閾値 |
| `similarity.method` | `cosine` | `cosine` または `jaccard` |
| `x_posts.count_per_source` | `3` | 1記事あたりのX投稿案生成数 |
| `ai.model` | `claude-opus-4-6` | 使用するClaudeモデル |

---

## 実行コマンド

すべて**プロジェクトルート**から実行してください。

### フルパイプライン実行（取得→生成→承認キュー保存）

```bash
python src/main.py
```

### 承認キューのインタラクティブレビュー

```bash
python src/main.py --approve
```

各アイテムに対して `y`（承認）/ `n`（却下）/ `s`（スキップ）/ `q`（終了）で操作します。

### 承認済みアイテムのファイル出力

```bash
python src/main.py --export
```

- X投稿案 → `data/drafts/x_posts/*.txt`
- note下書き → `data/drafts/notes/*.md`

### まとめて実行（パイプライン → レビュー → 出力）

```bash
python src/main.py --all
```

---

## 各ファイルの役割

| ファイル | 役割 |
|---|---|
| `src/main.py` | パイプライン全体のオーケストレーション・CLIエントリポイント |
| `src/models.py` | `Source` `RawArticle` `Summary` `StructuredContent` `XPost` `NoteDraft` `ApprovalItem` のデータモデル定義 |
| `src/fetch/fetch_sources.py` | `sources.yaml` 読み込み・プラットフォーム別フェッチャーへのディスパッチ。ダミーデータ内蔵 |
| `src/fetch/parse_article.py` | 生データを `RawArticle` に正規化。URL先の本文取得も試みる |
| `src/process/summarize.py` | Claude API（またはダミー）で日本語要約を生成。JSONで構造化出力 |
| `src/process/structure.py` | 要約を「思想・実装・示唆」の3レンズで再構造化 |
| `src/process/dedupe.py` | 過去の処理済みサマリーとの類似度チェック。しきい値超えは棄却 |
| `src/generate/x_writer.py` | X投稿案を3パターン（問いかけ・事実・洞察）で生成 |
| `src/generate/note_writer.py` | note.com向けMarkdown下書きを生成。有料/無料ゾーン分割対応 |
| `src/review/approval_queue.py` | `approval_queue.json` の管理。CLIインタラクティブレビュー機能 |
| `src/publish/export_x_posts.py` | 承認済みX投稿案を `data/drafts/x_posts/` にtxt出力 |
| `src/publish/export_note_md.py` | 承認済みnote下書きを `data/drafts/notes/` にmd出力（YAML front matter付き）|
| `src/utils/logger.py` | ログ設定。コンソール＋日付別ファイルに同時出力 |
| `src/utils/fileio.py` | YAML/JSON/テキストの読み書きユーティリティ |
| `src/utils/similarity.py` | コサイン類似度・Jaccard類似度。日本語対応のキャラクターn-gram方式 |
| `prompts/*.md` | Claude API呼び出し用プロンプトテンプレート。`{変数}` でパラメータを注入 |

---

## 動作フロー詳細

```
python src/main.py
 │
 ├─ [1] load_sources()          sources.yaml → List[Source]
 ├─ [2] fetch_source()          各ソースから生記事dict取得（現在はダミー）
 ├─ [3] parse_article()         生dictをRawArticleに正規化
 ├─ [4] summarize_article()     Claude APIで日本語要約 → Summary
 ├─ [5] check_duplicate()       過去サマリーと類似度比較 → 重複なら棄却
 ├─ [6] structure_content()     Claude APIで思想・実装・示唆に再構造化 → StructuredContent
 ├─ [7] generate_x_posts()      Claude APIでX投稿案3件生成 → List[XPost]
 ├─ [8] generate_note_draft()   Claude APIでnote下書き生成 → NoteDraft
 └─ [9] queue.add_item()        承認キューにpendingとして保存

python src/main.py --approve
 └─ run_interactive_review()    CLIでy/n/sを入力して承認/却下/スキップ

python src/main.py --export
 ├─ export_approved_x_posts()   data/drafts/x_posts/ にtxt出力
 └─ export_approved_notes()     data/drafts/notes/ にmd出力
```

---

## 将来の拡張ポイント

### 実ソース対応
- **RSS**: `feedparser` を使い `src/fetch/fetch_sources.py` の `fetch_rss()` を実装
- **Webスクレイピング**: `requests` + `BeautifulSoup` で `fetch_web()` を実装（`parse_article.py` に `_try_fetch_body_from_url()` の雛形あり）
- **X API**: X API v2 で `fetch_x()` を実装

### 定期実行
**GitHub Actions**（推奨）:
```yaml
# .github/workflows/ai-news.yml
on:
  schedule:
    - cron: '0 1 * * *'   # 毎日 JST 10:00
jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install -r requirements.txt
      - run: python src/main.py
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

**cron（ローカル）**:
```
0 1 * * * cd /path/to/project && python src/main.py >> data/logs/cron.log 2>&1
```

### X自動投稿（将来）
`src/publish/export_x_posts.py` に X API v2 (`tweepy`) を使った投稿関数を追加し、
`main.py` の `--post-x` フラグで呼び出す。

### note自動投稿（将来）
note.com API が公開された際に `src/publish/export_note_md.py` を拡張。

### 改善ポイント
- [ ] RSS/HTML フェッチャーの本実装（`feedparser` + `BeautifulSoup`）
- [ ] 既処理記事のURL管理（`data/state/seen_urls.json`）で重複フェッチを防止
- [ ] Web UIレビュー（Flask/FastAPI）で承認フローを改善
- [ ] Slack/Discord通知で新着アイテムをプッシュ通知
- [ ] 要約品質スコアリングによる自動フィルタリング
- [ ] 複数LLMプロバイダ対応（OpenAI, Gemini など）

---

## トラブルシューティング

**Q: `ModuleNotFoundError` が出る**
A: `python src/main.py` をプロジェクトルートから実行しているか確認してください。

**Q: ダミーデータしか生成されない**
A: `.env` に `ANTHROPIC_API_KEY` が設定されているか確認してください。

**Q: 毎回同じ記事が重複検出される**
A: `data/state/processed_summaries.json` を削除するとデュープ履歴がリセットされます。

**Q: `config/settings.yaml` の設定を変えても反映されない**
A: ファイルを保存後、再度 `python src/main.py` を実行してください。

---

## ライセンス

MIT
