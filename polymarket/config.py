"""
Polymarket Tracker - 設定ファイル
APIエンドポイント、定数、パスなどを定義
"""

# ===== Polymarket API エンドポイント =====

# リーダーボード取得 (上位トレーダーのランキング)
LEADERBOARD_URL = "https://data-api.polymarket.com/leaderboard"

# ユーザーのアクティビティ (取引履歴) 取得
ACTIVITY_URL = "https://data-api.polymarket.com/activity"

# マーケット情報取得 (Gamma API)
MARKETS_URL = "https://gamma-api.polymarket.com/markets"


# ===== トラッキング設定 =====

# 追跡する上位者の人数
TOP_N = 10

# スポーツ関連マーケットを判定するタグ
SPORTS_TAGS = ["nba", "nfl", "mlb", "nhl", "sports"]

# タイトルにこれらの文字列が含まれていればスポーツ関連と判定
SPORTS_KEYWORDS = ["NBA", "NFL", "MLB", "NHL", "vs", "Will"]


# ===== データ保存パス =====

# 取引履歴CSVの保存先
DATA_PATH = "data/trades.csv"

# リーダーボードJSONの保存先
LEADERBOARD_PATH = "leaderboard.json"


# ===== HTTP / リトライ設定 =====

# APIリトライ回数
RETRY_COUNT = 3

# リトライ間隔 (秒)
RETRY_INTERVAL = 1.0

# レート制限回避のリクエスト間スリープ (秒)
REQUEST_SLEEP = 0.5

# HTTPタイムアウト (秒)
REQUEST_TIMEOUT = 15


# ===== スケジューラ設定 =====

# 収集の実行間隔 (時間)
SCHEDULE_INTERVAL_HOURS = 1
