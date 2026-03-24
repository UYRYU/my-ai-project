"""Polymarket市場取得の動作確認スクリプト.

1. Gamma API からアクティブなイベント/市場を取得
2. BTC関連の短期市場を抽出
3. 全取得市場のうちBTC関連も一覧表示
4. 各市場のtoken_id, question, slug等を見やすく出力

Usage:
    python scripts/check_markets.py          # ライブAPI接続
    python scripts/check_markets.py --demo   # デモデータで動作確認
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_config
from src.market_discovery import BTC_KEYWORDS, SHORT_TERM_KEYWORDS, MarketDiscovery

DIVIDER = "=" * 80
THIN_DIVIDER = "-" * 80

# ── Demo data: realistic mock events ──
DEMO_EVENTS: list[dict] = [
    {
        "id": "evt-001",
        "title": "Bitcoin 5-Minute Price Markets",
        "slug": "bitcoin-5-minute-price",
        "active": True,
        "closed": False,
        "markets": [
            {
                "condition_id": "0xabc123def456789000000000000000000000000000000000000000000000001",
                "question": "Will Bitcoin be above $100,000 at 12:05 PM ET? (5-minute market)",
                "market_slug": "btc-above-100k-5min-1205",
                "active": True,
                "closed": False,
                "volume": "52340.50",
                "tokens": [
                    {"token_id": "71321045009812370000000000000000000000000000000000000000000001", "outcome": "Yes", "price": "0.62"},
                    {"token_id": "71321045009812370000000000000000000000000000000000000000000002", "outcome": "No", "price": "0.40"},
                ],
            },
            {
                "condition_id": "0xabc123def456789000000000000000000000000000000000000000000000002",
                "question": "Will Bitcoin be above $100,500 at 12:05 PM ET? (5-minute market)",
                "market_slug": "btc-above-100500-5min-1205",
                "active": True,
                "closed": False,
                "volume": "31200.00",
                "tokens": [
                    {"token_id": "71321045009812370000000000000000000000000000000000000000000003", "outcome": "Yes", "price": "0.35"},
                    {"token_id": "71321045009812370000000000000000000000000000000000000000000004", "outcome": "No", "price": "0.67"},
                ],
            },
        ],
    },
    {
        "id": "evt-002",
        "title": "Bitcoin 1-Minute Price Markets",
        "slug": "bitcoin-1-minute-price",
        "active": True,
        "closed": False,
        "markets": [
            {
                "condition_id": "0xdef789abc123456000000000000000000000000000000000000000000000003",
                "question": "Will BTC go up in the next 1-minute candle?",
                "market_slug": "btc-1min-up-candle",
                "active": True,
                "closed": False,
                "volume": "8750.25",
                "tokens": [
                    {"token_id": "88432045009812370000000000000000000000000000000000000000000001", "outcome": "Yes", "price": "0.51"},
                    {"token_id": "88432045009812370000000000000000000000000000000000000000000002", "outcome": "No", "price": "0.50"},
                ],
            },
        ],
    },
    {
        "id": "evt-003",
        "title": "US Presidential Election 2028",
        "slug": "us-presidential-election-2028",
        "active": True,
        "closed": False,
        "markets": [
            {
                "condition_id": "0x999888777666555000000000000000000000000000000000000000000000004",
                "question": "Will the Democratic nominee win the 2028 presidential election?",
                "market_slug": "dem-nominee-win-2028",
                "active": True,
                "closed": False,
                "volume": "1250000.00",
                "tokens": [
                    {"token_id": "99555045009812370000000000000000000000000000000000000000000001", "outcome": "Yes", "price": "0.45"},
                    {"token_id": "99555045009812370000000000000000000000000000000000000000000002", "outcome": "No", "price": "0.56"},
                ],
            },
        ],
    },
    {
        "id": "evt-004",
        "title": "Bitcoin Year-End Price",
        "slug": "bitcoin-year-end-price",
        "active": True,
        "closed": False,
        "markets": [
            {
                "condition_id": "0xfff111222333444000000000000000000000000000000000000000000000005",
                "question": "Will Bitcoin be above $150,000 on December 31?",
                "market_slug": "btc-above-150k-eoy",
                "active": True,
                "closed": False,
                "volume": "875000.00",
                "tokens": [
                    {"token_id": "66777045009812370000000000000000000000000000000000000000000001", "outcome": "Yes", "price": "0.28"},
                    {"token_id": "66777045009812370000000000000000000000000000000000000000000002", "outcome": "No", "price": "0.73"},
                ],
            },
        ],
    },
]

DEMO_ORDER_BOOK: dict = {
    "bids": [
        {"price": "0.60", "size": "250.00"},
        {"price": "0.59", "size": "500.00"},
        {"price": "0.58", "size": "180.00"},
        {"price": "0.55", "size": "1200.00"},
    ],
    "asks": [
        {"price": "0.62", "size": "300.00"},
        {"price": "0.63", "size": "450.00"},
        {"price": "0.65", "size": "200.00"},
        {"price": "0.70", "size": "800.00"},
    ],
}


def print_events_sample(all_events: list[dict]) -> None:
    """Step 2: Show a few raw events as sample."""
    print(f"\n[2/4] 最初の3イベント（生データサンプル）")
    print(THIN_DIVIDER)
    for i, event in enumerate(all_events[:3]):
        markets_in_event = event.get("markets", [])
        print(f"  Event #{i+1}")
        print(f"    title:    {event.get('title', 'N/A')[:80]}")
        print(f"    slug:     {event.get('slug', 'N/A')}")
        print(f"    active:   {event.get('active')}")
        print(f"    closed:   {event.get('closed')}")
        print(f"    markets:  {len(markets_in_event)} 件")
        if markets_in_event:
            m0 = markets_in_event[0]
            print(f"    market[0] question: {m0.get('question', 'N/A')[:70]}")
            tokens = m0.get("tokens", [])
            if isinstance(tokens, str):
                tokens = json.loads(tokens)
            for t in tokens[:2]:
                print(f"      token: {t.get('outcome', '?')} | id={t.get('token_id', '?')[:20]}... | price={t.get('price', '?')}")
        print()


def filter_btc_markets(all_events: list[dict]) -> tuple[list[dict], list[dict]]:
    """Step 3: Filter BTC markets."""
    btc_markets: list[dict] = []
    btc_all: list[dict] = []
    for event in all_events:
        for m in event.get("markets", []):
            q = (m.get("question") or "").lower()
            is_btc = any(kw in q for kw in BTC_KEYWORDS)
            is_short = any(kw in q for kw in SHORT_TERM_KEYWORDS)
            if is_btc:
                btc_all.append(m)
                if is_short:
                    btc_markets.append(m)
    return btc_all, btc_markets


def print_btc_markets(btc_all: list[dict], gamma_url: str) -> None:
    """Print BTC related markets."""
    if btc_all:
        print(f"\n  -- BTC関連市場 全 {len(btc_all)} 件 --")
        print(THIN_DIVIDER)
        for i, m in enumerate(btc_all[:20]):
            q = m.get("question", "N/A")
            slug = m.get("market_slug", m.get("slug", "N/A"))
            active = m.get("active")
            closed = m.get("closed")
            volume = m.get("volume", "N/A")
            tokens = m.get("tokens", [])
            if isinstance(tokens, str):
                tokens = json.loads(tokens)
            cond_id = m.get("condition_id", "N/A")

            short_match = any(kw in q.lower() for kw in SHORT_TERM_KEYWORDS)
            tag = " [SHORT-TERM]" if short_match else ""

            print(f"\n  #{i+1}{tag}")
            print(f"    question:     {q[:75]}")
            print(f"    slug:         {slug}")
            print(f"    condition_id: {cond_id[:24]}...")
            print(f"    active: {active}  closed: {closed}  volume: {volume}")
            for t in tokens[:2]:
                tid = t.get("token_id", "?")
                print(f"    token [{t.get('outcome', '?'):3}]: {tid[:24]}...  price={t.get('price', '?')}")

        if len(btc_all) > 20:
            print(f"\n  ... 他 {len(btc_all) - 20} 件省略")
    else:
        print("\n  *** BTC関連市場が見つかりませんでした ***")
        print("  Polymarketに現在BTC短期市場がない可能性があります。")
        print("  キーワードを広げるか、手動で確認してください:")
        print(f"    {gamma_url}/events?active=true&closed=false&limit=10")


def find_test_token(btc_markets: list[dict], btc_all: list[dict], all_events: list[dict]) -> tuple[str | None, str]:
    """Find a token_id for order book test."""
    for m in (btc_markets or btc_all or []):
        tokens = m.get("tokens", [])
        if isinstance(tokens, str):
            tokens = json.loads(tokens)
        if tokens:
            return tokens[0].get("token_id"), m.get("question", "")[:60]

    if all_events:
        for event in all_events:
            for m in event.get("markets", []):
                tokens = m.get("tokens", [])
                if isinstance(tokens, str):
                    tokens = json.loads(tokens)
                if tokens:
                    return tokens[0].get("token_id"), m.get("question", "")[:60]
    return None, ""


async def run_live() -> None:
    """Live mode: fetch from real Polymarket API."""
    config = load_config()
    discovery = MarketDiscovery(config)

    print(DIVIDER)
    print("  Polymarket 市場取得チェック [LIVE]")
    print(f"  実行時刻: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"  Gamma API: {config.gamma_api}")
    print(f"  CLOB API:  {config.clob_api}")
    print(DIVIDER)

    # Step 1
    print("\n[1/4] Gamma API /events からアクティブイベントを取得中...")
    all_events = await discovery.fetch_events(offset=0, limit=100)
    print(f"  -> 取得イベント数: {len(all_events)}")

    if not all_events:
        print("\n  *** イベントが0件です。API接続を確認してください。 ***")
        print(f"  テストURL: {config.gamma_api}/events?active=true&closed=false&limit=5")
        print(f"\n  ヒント: --demo フラグでデモデータ動作確認ができます:")
        print(f"    python scripts/check_markets.py --demo")
        await discovery.close()
        return

    total_markets = sum(len(e.get("markets", [])) for e in all_events)
    print(f"  -> イベント内の市場数合計: {total_markets}")

    # Step 2
    print_events_sample(all_events)

    # Step 3
    print(f"[3/4] BTC関連市場を抽出中...")
    print(f"  BTC キーワード: {BTC_KEYWORDS}")
    print(f"  短期キーワード: {SHORT_TERM_KEYWORDS}")
    btc_all, btc_markets = filter_btc_markets(all_events)
    print(f"\n  BTC関連 (全件):         {len(btc_all)} 件")
    print(f"  BTC関連 + 短期フィルタ: {len(btc_markets)} 件")
    print_btc_markets(btc_all, config.gamma_api)

    # Step 4
    print(f"\n[4/4] CLOB API 板情報テスト...")
    test_token, test_question = find_test_token(btc_markets, btc_all, all_events)

    if test_token:
        print(f"  市場: {test_question}")
        print(f"  token_id: {test_token[:24]}...")
        book = await discovery.fetch_order_book(test_token)
        if book.bids or book.asks:
            print(f"  bids: {len(book.bids)} 件  asks: {len(book.asks)} 件")
            if book.best_bid is not None:
                print(f"  best bid: {book.best_bid:.4f} (size={book.best_bid_size:.2f})")
            if book.best_ask is not None:
                print(f"  best ask: {book.best_ask:.4f} (size={book.best_ask_size:.2f})")
            if book.spread is not None:
                print(f"  spread:   {book.spread:.4f}")
        else:
            print("  -> 板情報が空です（市場がまだ流動性がない可能性）")
    else:
        print("  テスト対象のtokenが見つかりませんでした")

    await discovery.close()

    # Summary
    print(f"\n{DIVIDER}")
    print("  まとめ")
    print(DIVIDER)
    print(f"  Gamma API イベント取得:  {'OK' if all_events else 'NG'} ({len(all_events)} events)")
    print(f"  市場数:                  {total_markets}")
    print(f"  BTC関連:                 {len(btc_all)}")
    print(f"  BTC短期:                 {len(btc_markets)}")
    print(f"  CLOB板取得:              {'OK' if test_token else 'SKIP'}")
    print(DIVIDER)

    if not btc_markets:
        print("\n  NOTE: BTC短期市場が0件の場合、Polymarketに該当市場が現在")
        print("  存在しない可能性があります。bot起動時はポーリングで継続監視します。")
        print("  キーワードを .env や market_discovery.py で調整可能です。")
    print()


async def run_demo() -> None:
    """Demo mode: use mock data to verify script logic."""
    from src.models import OrderBookLevel, OrderBookSnapshot

    print(DIVIDER)
    print("  Polymarket 市場取得チェック [DEMO MODE]")
    print(f"  実行時刻: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"  ※ デモデータを使用しています（API接続なし）")
    print(DIVIDER)

    all_events = DEMO_EVENTS

    # Step 1
    print(f"\n[1/4] デモイベントをロード...")
    print(f"  -> 取得イベント数: {len(all_events)}")
    total_markets = sum(len(e.get("markets", [])) for e in all_events)
    print(f"  -> イベント内の市場数合計: {total_markets}")

    # Step 2
    print_events_sample(all_events)

    # Step 3
    print(f"[3/4] BTC関連市場を抽出中...")
    print(f"  BTC キーワード: {BTC_KEYWORDS}")
    print(f"  短期キーワード: {SHORT_TERM_KEYWORDS}")
    btc_all, btc_markets = filter_btc_markets(all_events)
    print(f"\n  BTC関連 (全件):         {len(btc_all)} 件")
    print(f"  BTC関連 + 短期フィルタ: {len(btc_markets)} 件")
    print_btc_markets(btc_all, "https://gamma-api.polymarket.com")

    # Step 4
    print(f"\n[4/4] CLOB API 板情報テスト (デモデータ)...")
    test_token, test_question = find_test_token(btc_markets, btc_all, all_events)

    if test_token:
        print(f"  市場: {test_question}")
        print(f"  token_id: {test_token[:24]}...")

        # Parse demo order book
        bids = [OrderBookLevel(price=float(b["price"]), size=float(b["size"])) for b in DEMO_ORDER_BOOK["bids"]]
        asks = [OrderBookLevel(price=float(a["price"]), size=float(a["size"])) for a in DEMO_ORDER_BOOK["asks"]]
        bids.sort(key=lambda x: x.price, reverse=True)
        asks.sort(key=lambda x: x.price)
        book = OrderBookSnapshot(bids=bids, asks=asks)

        print(f"  bids: {len(book.bids)} 件  asks: {len(book.asks)} 件")
        if book.best_bid is not None:
            print(f"  best bid: {book.best_bid:.4f} (size={book.best_bid_size:.2f})")
        if book.best_ask is not None:
            print(f"  best ask: {book.best_ask:.4f} (size={book.best_ask_size:.2f})")
        if book.spread is not None:
            print(f"  spread:   {book.spread:.4f}")

    # Summary
    print(f"\n{DIVIDER}")
    print("  まとめ")
    print(DIVIDER)
    print(f"  Gamma API イベント取得:  DEMO ({len(all_events)} events)")
    print(f"  市場数:                  {total_markets}")
    print(f"  BTC関連:                 {len(btc_all)}")
    print(f"  BTC短期:                 {len(btc_markets)}")
    print(f"  CLOB板取得:              DEMO")
    print(DIVIDER)
    print()
    print("  ライブAPIに接続する場合:")
    print("    python scripts/check_markets.py")
    print()


async def main() -> None:
    if "--demo" in sys.argv:
        await run_demo()
    else:
        await run_live()


if __name__ == "__main__":
    asyncio.run(main())
