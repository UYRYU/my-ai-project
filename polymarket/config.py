"""
Polymarket Tracker - 設定ファイル
APIエンドポイント、定数、パスなどを定義
"""

# ===== Polymarket API エンドポイント =====

# リーダーボード取得 (v1 エンドポイント)
LEADERBOARD_URL = "https://data-api.polymarket.com/v1/leaderboard"

# ユーザーのアクティビティ (取引履歴) 取得
ACTIVITY_URL = "https://data-api.polymarket.com/activity"

# マーケット情報取得 (Gamma API)
MARKETS_URL = "https://gamma-api.polymarket.com/markets"

# CLOB API (マーケットの勝敗判定に使用。tokens[].winner が明示的にある)
CLOB_URL = "https://clob.polymarket.com/markets"


# ===== トラッキング設定 =====

# 追跡する上位者の人数 (各ウィンドウごと)
TOP_N = 10

# スポーツ関連マーケットを判定するタグ
SPORTS_TAGS = ["nba", "nfl", "mlb", "nhl", "sports"]

# タイトルにこれらの文字列が含まれていればスポーツ関連と判定
SPORTS_KEYWORDS = ["NBA", "NFL", "MLB", "NHL", "vs", "Will"]

# リーダーボードのウィンドウ (API パラメータ: timePeriod)
# Polymarket v1 API がサポートする値: DAY, WEEK, MONTH, ALL
WINDOWS = ["DAY", "WEEK", "MONTH", "ALL"]

# ウィンドウの表示名 (ログ/レポート用)
WINDOW_LABELS = {
    "DAY": "日次",
    "WEEK": "週次",
    "MONTH": "月次",
    "ALL": "全期間",
}

# リーダーボード種別 (API パラメータ: orderBy)
# PNL=利益順, VOL=取引量順
LEADERBOARD_TYPES = ["PNL", "VOL"]

# collect_all で追跡対象とするウィンドウ
TRACK_WINDOWS = ["DAY", "WEEK", "ALL"]

# collect_all で追跡対象とする種別
# PNL (利益順) のみに絞る。VOL は取引量が多いだけで勝ってない人も混ざるため除外。
TRACK_TYPES = ["PNL"]

# カテゴリフィルタ (API パラメータ: category)
# OVERALL, POLITICS, SPORTS, CRYPTO, CULTURE, MENTIONS, WEATHER, ECONOMICS, TECH, FINANCE
LEADERBOARD_CATEGORY = "SPORTS"


# ===== データ保存パス =====

# 取引履歴CSVの保存先
DATA_PATH = "data/trades.csv"

# リーダーボードJSONの保存先 (単一ウィンドウ用 - 互換性のため残す)
LEADERBOARD_PATH = "leaderboard.json"

# 複数ウィンドウのリーダーボードをまとめて保存するディレクトリ
LEADERBOARD_DIR = "data/leaderboards"


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
