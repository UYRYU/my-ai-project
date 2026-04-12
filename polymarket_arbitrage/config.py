"""Configuration constants."""

# Polymarket Gamma API
GAMMA_API_BASE = "https://gamma-api.polymarket.com"
GAMMA_EVENTS_ENDPOINT = f"{GAMMA_API_BASE}/events"
GAMMA_MARKETS_ENDPOINT = f"{GAMMA_API_BASE}/markets"

# Rate limits (per 10 seconds)
GAMMA_RATE_LIMIT_EVENTS = 500
GAMMA_RATE_LIMIT_MARKETS = 300

# Default fetch params
DEFAULT_FETCH_LIMIT = 100

# Arbitrage detection thresholds
# Minimum price deviation from $1.00 to flag as arbitrage opportunity
MIN_ARBITRAGE_THRESHOLD = 0.01  # $0.01
# Polymarket trading fee (2% on winnings, not on investment)
TRADING_FEE_RATE = 0.02

# Topic classification
TOPICS = [
    "Politics",
    "Economy",
    "Technology",
    "Crypto",
    "Twitter",
    "Culture",
    "Sports",
]

# Embedding model (paper uses Linq-Embed-Mistral; we default to a lighter model
# but allow override via env var for users who have access)
DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# Cosine similarity threshold for considering markets related
SIMILARITY_THRESHOLD = 0.75

# Temporal proximity: max days apart for markets to be considered related
MAX_TEMPORAL_DISTANCE_DAYS = 30
