# Bybit SIREN/USDT スキャルピングボット設定

# === Bybit API設定 ===
API_KEY = ""        # BybitのAPIキーを入力
API_SECRET = ""     # BybitのAPIシークレットを入力

# === 取引ペア (複数対応) ===
# メイン通貨
SYMBOL = "SIRENUSDT"
# サブ通貨 (分散運用する場合)
# SYMBOL = "RDNTUSDT"
# SYMBOL = "VANRYUSDT"

# === 通貨別最適パラメータ ===
PARAMS = {
    "SIRENUSDT": {"tp": 1.5, "sl": 0.3, "bb_period": 20, "bb_std": 2.0},
    "RDNTUSDT":  {"tp": 2.5, "sl": 1.0, "bb_period": 20, "bb_std": 2.0},
    "VANRYUSDT": {"tp": 1.5, "sl": 0.8, "bb_period": 20, "bb_std": 2.0},
    "ATHUSDT":   {"tp": 1.5, "sl": 1.0, "bb_period": 20, "bb_std": 2.0},
    "JTOUSDT":   {"tp": 0.5, "sl": 0.5, "bb_period": 20, "bb_std": 2.0},
    "ARCUSDT":   {"tp": 1.0, "sl": 0.8, "bb_period": 20, "bb_std": 2.0},
}

# === レバレッジ・マージン ===
LEVERAGE = 5
MARGIN_MODE = "cross"    # "cross" or "isolated"

# === 注文設定 ===
# 資金の何%を1回の取引に使うか (証拠金ベース)
POSITION_SIZE_PCT = 30   # 資金の30%
# または固定数量 (0より大きい場合、POSITION_SIZE_PCTより優先)
FIXED_QTY = 0            # 0=自動計算

# === レンジ計算 ===
TIMEFRAME = "15"         # K線の足 (1, 3, 5, 15, 30, 60, 120, 240)
LOOKBACK = 96            # レンジ計算用のK線本数 (96本×15分=24h)
RANGE_UPDATE_SEC = 300   # レンジ再計算間隔 (秒)

# === エントリー条件 ===
ENTRY_OFFSET_PCT = 0.5   # レンジ端からのエントリー余裕 (%)
TREND_FILTER = False     # トレンドフィルター (True=トレンド中はエントリーしない)

# === リスク管理 ===
MAX_POSITIONS = 1        # 同時ポジション数
MAX_DAILY_TRADES = 50    # 1日の最大取引回数
MAX_DAILY_LOSS_PCT = 5.0 # 1日の最大損失率 (%)
COOLDOWN_SEC = 30        # 損切り後のクールダウン (秒)

# === スプレッドチェック ===
MAX_SPREAD_PCT = 0.3     # スプレッドがこれ以上ならエントリーしない (%)

# === その他 ===
POLL_INTERVAL = 1        # 価格チェック間隔 (秒)
DRY_RUN = True           # True=デモモード (実注文なし)
LOG_FILE = "trades.log"  # トレードログファイル
