# MEXC SPACEX/USDT スキャルピングボット設定

# === MEXC API設定 ===
API_KEY = ""       # MEXCのAPIキーを入力
API_SECRET = ""    # MEXCのAPIシークレットを入力

# === 取引ペア ===
SYMBOL = "SPACEX_USDT"          # MEXC先物シンボル
TIMEFRAME = "Min15"             # ボラ計算用の足 (Min1, Min5, Min15, Min30, Min60)
LOOKBACK_PERIODS = 20           # レンジ計算に使うローソク足の本数

# === スキャルピング設定 ===
ORDER_SIZE = 1                  # 1回の注文数量 (SPACEX枚数)
LEVERAGE = 10                   # レバレッジ倍率
MARGIN_MODE = "cross"           # cross or isolated

# === レンジ自動検出 ===
RANGE_METHOD = "bollinger"      # "bollinger" or "highlow"
BOLLINGER_PERIOD = 20           # ボリンジャーバンド期間
BOLLINGER_STD = 2.0             # ボリンジャーバンド標準偏差

# === エントリー条件 ===
ENTRY_OFFSET_PCT = 0.3          # レンジ端からエントリーまでの余裕 (%)
TAKE_PROFIT_PCT = 0.5           # 利確幅 (%)
STOP_LOSS_PCT = 0.8             # 損切り幅 (%)

# === レンジ更新 ===
RANGE_UPDATE_INTERVAL = 300     # レンジ再計算間隔 (秒)

# === リスク管理 ===
MAX_POSITIONS = 1               # 同時最大ポジション数
MAX_DAILY_TRADES = 50           # 1日の最大取引回数
MAX_DAILY_LOSS_USDT = 50.0      # 1日の最大損失額 (USDT)
COOLDOWN_AFTER_LOSS = 60        # 損切り後のクールダウン (秒)

# === その他 ===
POLL_INTERVAL = 2               # 価格チェック間隔 (秒)
DRY_RUN = True                  # True=デモモード(実際の注文なし)
