#!/usr/bin/env python3
"""Polymarket 市場取得の動作確認スクリプト.

Step 1: Gamma API /events でアクティブイベント取得
Step 2: CLOB API /markets でカーソルページネーション取得
Step 3: BTC 短期市場をフィルタリング
Step 4: CLOB API /book で板情報取得テスト

Usage:
    cd polymarket_bot
    python scripts/check_markets.py          # ライブAPI接続
    python scripts/check_markets.py --demo   # デモデータで動作確認
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_config
from src.market_discovery import BTC_KEYWORDS, SHORT_TERM_MAX_DAYS, MarketDiscovery
from src.models import OrderBookLevel, OrderBookSnapshot

DIV = "=" * 78
THIN = "-" * 78

# ────────────────────────────────────────────────
#  Demo fixtures
# ────────────────────────────────────────────────
DEMO_CLOB_PAGES: list[tuple[list[dict], str]] = [
    (
        [
            {
                "condition_id": "0xabc001",
                "question": "Will Bitcoin be above $100,000 at 12:05 PM ET? (5-minute market)",
                "market_slug": "btc-above-100k-5min-1205",
                "active": True,
                "end_date_iso": "2026-04-10T16:05:00Z",
                "volume": "52340.50",
                "tokens": [
                    {"token_id": "71321045000001", "outcome": "Yes", "price": "0.62"},
                    {"token_id": "71321045000002", "outcome": "No",  "price": "0.40"},
                ],
            },
            {
                "condition_id": "0xabc002",
                "question": "Will Bitcoin be above $100,500 at 12:05 PM ET? (5-minute market)",
                "market_slug": "btc-above-100500-5min-1205",
                "active": True,
                "end_date_iso": "2026-04-10T16:05:00Z",
                "volume": "31200.00",
                "tokens": [
                    {"token_id": "71321045000003", "outcome": "Yes", "price": "0.35"},
                    {"token_id": "71321045000004", "outcome": "No",  "price": "0.67"},
                ],
            },
            {
                "condition_id": "0xdef003",
                "question": "Will BTC go up in the next 1-minute candle?",
                "market_slug": "btc-1min-up-candle",
                "active": True,
                "end_date_iso": "2026-04-05T16:01:00Z",
                "volume": "8750.25",
                "tokens": [
                    {"token_id": "88432045000001", "outcome": "Yes", "price": "0.51"},
                    {"token_id": "88432045000002", "outcome": "No",  "price": "0.50"},
                ],
            },
            {
                "condition_id": "0x999004",
                "question": "Will the Democratic nominee win the 2028 presidential election?",
                "market_slug": "dem-nominee-win-2028",
                "active": True,
                "end_date_iso": "2028-11-05T00:00:00Z",
                "volume": "1250000.00",
                "tokens": [
                    {"token_id": "99555045000001", "outcome": "Yes", "price": "0.45"},
                    {"token_id": "99555045000002", "outcome": "No",  "price": "0.56"},
                ],
            },
            {
                "condition_id": "0xfff005",
                "question": "Will Bitcoin be above $150,000 on December 31?",
                "market_slug": "btc-above-150k-eoy",
                "active": True,
                "end_date_iso": "2026-12-31T23:59:59Z",
                "volume": "875000.00",
                "tokens": [
                    {"token_id": "66777045000001", "outcome": "Yes", "price": "0.28"},
                    {"token_id": "66777045000002", "outcome": "No",  "price": "0.73"},
                ],
            },
        ],
        "LTE",
    ),
]

DEMO_BOOK: dict = {
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


# ────────────────────────────────────────────────
#  Helpers
# ────────────────────────────────────────────────
def _tokens(raw: list | str) -> list[dict]:
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


def is_btc(q: str) -> bool:
    return any(kw in q for kw in BTC_KEYWORDS)


def is_short_term(m: dict) -> bool:
    """Check if market ends within SHORT_TERM_MAX_DAYS."""
    end_date = m.get("end_date_iso", m.get("end_date", ""))
    if not end_date:
        return True
    try:
        from datetime import datetime, timezone
        end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        days_left = (end_dt - datetime.now(timezone.utc)).days
        return 0 <= days_left <= SHORT_TERM_MAX_DAYS
    except (ValueError, TypeError):
        return True


def print_market_row(idx: int, m: dict) -> None:
    q = m.get("question", "N/A")
    slug = m.get("market_slug", m.get("slug", "N/A"))
    cond = m.get("condition_id", "?")
    active = m.get("active")
    closed = m.get("closed", False)
    vol = m.get("volume", "0")
    tokens = _tokens(m.get("tokens", []))
    ql = q.lower()
    tag = " [SHORT-TERM]" if (is_btc(ql) and is_short_term(m)) else ""

    print(f"\n  #{idx}{tag}")
    end = m.get("end_date_iso", m.get("end_date", "N/A"))
    print(f"    question:     {q[:75]}")
    print(f"    slug:         {slug}")
    print(f"    condition_id: {cond[:28]}{'...' if len(cond) > 28 else ''}")
    print(f"    active={active}  closed={closed}  volume={vol}  end_date={end}")
    for t in tokens[:2]:
        tid = t.get("token_id", "?")
        print(f"    token [{t.get('outcome','?'):3}]: {tid[:28]}{'...' if len(tid)>28 else ''}  price={t.get('price','?')}")


def print_book(book: OrderBookSnapshot) -> None:
    print(f"    bids: {len(book.bids)} levels  asks: {len(book.asks)} levels")
    if book.best_bid is not None:
        print(f"    best bid : {book.best_bid:.4f}  size={book.best_bid_size:.2f}")
    if book.best_ask is not None:
        print(f"    best ask : {book.best_ask:.4f}  size={book.best_ask_size:.2f}")
    if book.spread is not None:
        print(f"    spread   : {book.spread:.4f}")


# ────────────────────────────────────────────────
#  Live mode
# ────────────────────────────────────────────────
async def run_live() -> None:
    config = load_config()
    discovery = MarketDiscovery(config)

    print(DIV)
    print("  Polymarket 市場取得チェック [LIVE]")
    print(f"  {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"  Gamma API : {config.gamma_api}")
    print(f"  CLOB API  : {config.clob_api}")
    print(DIV)

    # ── Step 1: Gamma API ──
    print("\n[1/5] Gamma API /events ...")
    events = await discovery.fetch_events(offset=0, limit=10)
    gamma_ok = bool(events)
    gamma_market_count = sum(len(e.get("markets", [])) for e in events)
    print(f"  events={len(events)}  markets_in_events={gamma_market_count}  {'OK' if gamma_ok else 'FAILED (will use CLOB)'}")

    if gamma_ok:
        first_ev = events[0]
        print(f"  sample event: {first_ev.get('title','?')[:60]}")
    else:
        # Debug: try raw HTTP to see the error
        import httpx as _httpx
        try:
            async with _httpx.AsyncClient(timeout=10) as _c:
                _r = await _c.get(f"{config.gamma_api}/events", params={"active": "true", "limit": "1"})
                print(f"  [DEBUG] HTTP {_r.status_code}  body={_r.text[:200]}")
        except Exception as _e:
            print(f"  [DEBUG] connection error: {_e}")

    # ── Step 1b: Gamma API /markets (BTC search) ──
    print("\n[2/5] Gamma API /markets (tag=crypto, BTC search) ...")
    gamma_btc_markets: list[dict] = []
    try:
        gamma_client = await discovery._get_gamma_client()
        for search_tag in ["Bitcoin", "BTC"]:
            resp = await gamma_client.get("/markets", params={
                "active": "true",
                "closed": "false",
                "tag": "crypto",
                "limit": "100",
            })
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    gamma_btc_markets.extend(data)
                    print(f"  tag=crypto: {len(data)} markets")
                break
            else:
                print(f"  HTTP {resp.status_code}")
    except Exception as e:
        print(f"  error: {e}")
    print(f"  Gamma /markets total: {len(gamma_btc_markets)}")

    # ── Step 3: CLOB API (active only) ──
    print("\n[3/5] CLOB API /markets (active=true, up to 10 pages) ...")
    all_clob_raw: list[dict] = []
    cursor = "MA=="
    for page_i in range(10):
        page_data, cursor = await discovery.fetch_clob_markets(cursor, active=True)
        all_clob_raw.extend(page_data)
        print(f"  page {page_i+1}: {len(page_data)} markets  next_cursor={cursor[:12]}{'...' if len(cursor)>12 else ''}")
        if cursor == "LTE" or not page_data:
            break
    clob_ok = bool(all_clob_raw)
    print(f"  total from CLOB (sampled): {len(all_clob_raw)}  {'OK' if clob_ok else 'FAILED'}")

    if not gamma_ok and not clob_ok:
        print(f"\n  *** 両APIに接続できませんでした ***")
        print(f"  ネットワーク/プロキシを確認してください。")
        print(f"  デモモード: python scripts/check_markets.py --demo")
        await discovery.close()
        return

    # ── Step 4: BTC filtering ──
    print(f"\n[4/5] BTC短期市場を抽出 ...")
    print(f"  BTC keywords:     {BTC_KEYWORDS}")
    print(f"  短期判定:         end_date が {SHORT_TERM_MAX_DAYS}日以内")

    # Collect raw markets from all sources
    combined_raw: list[dict] = []
    if gamma_ok:
        for ev in events:
            combined_raw.extend(ev.get("markets", []))
    combined_raw.extend(gamma_btc_markets)
    combined_raw.extend(all_clob_raw)

    # Deduplicate by condition_id and filter out closed/expired markets
    seen: set[str] = set()
    unique_raw: list[dict] = []
    skipped_closed = 0
    skipped_expired = 0
    for m in combined_raw:
        cid = m.get("condition_id", "")
        if cid and cid not in seen:
            seen.add(cid)
            if m.get("closed") is True:
                skipped_closed += 1
                continue
            # Filter by end_date: skip markets with end_date in the past
            end_str = m.get("end_date_iso") or m.get("end_date") or ""
            if end_str and end_str != "N/A":
                try:
                    end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                    if end_dt < datetime.now(end_dt.tzinfo):
                        skipped_expired += 1
                        continue
                except (ValueError, TypeError):
                    pass
            unique_raw.append(m)
    print(f"  フィルタ: closed={skipped_closed}件除外, expired={skipped_expired}件除外")

    btc_all = [m for m in unique_raw if is_btc((m.get("question") or "").lower())]

    btc_short = [m for m in btc_all if is_short_term(m)]

    print(f"\n  全ユニーク市場:          {len(unique_raw)}")
    print(f"  BTC関連:                 {len(btc_all)}")
    print(f"  BTC関連 + 短期:          {len(btc_short)}")

    # Show ALL BTC markets with their date info
    if btc_all:
        print(f"\n  ┌─ BTC関連 全{len(btc_all)}件の詳細 ─┐")
        for di, m in enumerate(btc_all, 1):
            q = (m.get("question") or "")[:70]
            end1 = m.get("end_date_iso", "")
            end2 = m.get("end_date", "")
            end3 = m.get("closed", "")
            short = is_short_term(m)
            tag = "★短期" if short else "  長期/期限切れ"
            print(f"  {di:2d}. [{tag}] {q}")
            print(f"      end_date_iso={end1!r}  end_date={end2!r}  closed={end3!r}")

    display = btc_all if btc_all else unique_raw[:10]
    label = "BTC関連市場" if btc_all else "全市場サンプル (BTC見つからず)"
    print(f"\n  -- {label} ({len(display)} 件) --")
    print(THIN)
    for i, m in enumerate(display[:20], 1):
        print_market_row(i, m)
    if len(display) > 20:
        print(f"\n  ... 他 {len(display)-20} 件省略")

    # ── Step 5: Order book test ──
    print(f"\n[5/5] CLOB API /book テスト ...")
    test_token = None
    test_q = ""
    for m in (btc_short or btc_all or unique_raw[:5]):
        tokens = _tokens(m.get("tokens", []))
        if tokens and tokens[0].get("token_id"):
            test_token = tokens[0]["token_id"]
            test_q = (m.get("question") or "")[:60]
            break

    if test_token:
        print(f"  market:   {test_q}")
        print(f"  token_id: {test_token[:28]}...")
        book = await discovery.fetch_order_book(test_token)
        if book.bids or book.asks:
            print_book(book)
            book_ok = True
        else:
            print("    -> 板データ空（流動性なし or エンドポイントエラー）")
            book_ok = False
    else:
        print("  テスト対象トークンなし")
        book_ok = False

    await discovery.close()

    # ── Summary ──
    print(f"\n{DIV}")
    print("  結果サマリー")
    print(DIV)
    print(f"  Gamma API /events   : {'OK' if gamma_ok else 'NG'}  ({gamma_market_count} markets)")
    print(f"  CLOB API  /markets  : {'OK' if clob_ok else 'NG'}  ({len(all_clob_raw)} markets sampled)")
    print(f"  BTC関連             : {len(btc_all)}")
    print(f"  BTC短期             : {len(btc_short)}")
    print(f"  CLOB /book          : {'OK' if book_ok else 'NG/EMPTY'}")
    print(DIV)

    if not btc_short:
        print("\n  NOTE: BTC短期市場が0件の場合、Polymarketに現在該当市場がないか、")
        print("  キーワードが合っていない可能性があります。")
        print("  src/market_discovery.py の BTC_KEYWORDS / SHORT_TERM_KEYWORDS を調整してください。")
    print()


# ────────────────────────────────────────────────
#  Demo mode
# ────────────────────────────────────────────────
async def run_demo() -> None:
    print(DIV)
    print("  Polymarket 市場取得チェック [DEMO]")
    print(f"  {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print("  ※ デモデータ使用（API接続なし）")
    print(DIV)

    # Step 1 — skip Gamma
    print("\n[1/4] Gamma API /events ... SKIP (demo)")

    # Step 2 — CLOB mock
    print("\n[2/4] CLOB API /markets (デモ) ...")
    all_raw, cursor = DEMO_CLOB_PAGES[0]
    print(f"  page 1: {len(all_raw)} markets  next_cursor={cursor}")
    print(f"  total from CLOB (sampled): {len(all_raw)}  OK")

    # Step 3 — filter
    print(f"\n[3/4] BTC短期市場を抽出 ...")
    print(f"  BTC keywords:     {BTC_KEYWORDS}")
    print(f"  短期判定:         end_date が {SHORT_TERM_MAX_DAYS}日以内")

    btc_all = [m for m in all_raw if is_btc((m.get("question") or "").lower())]
    btc_short = [m for m in btc_all if is_short_term(m)]
    print(f"  全市場:                  {len(all_raw)}")
    print(f"  BTC関連:                 {len(btc_all)}")
    print(f"  BTC関連 + 短期:          {len(btc_short)}")

    print(f"\n  -- BTC関連市場 ({len(btc_all)} 件) --")
    print(THIN)
    for i, m in enumerate(btc_all, 1):
        print_market_row(i, m)

    # Step 4 — book mock
    print(f"\n[4/4] CLOB API /book テスト (デモ) ...")
    first_token = _tokens(btc_short[0]["tokens"])[0] if btc_short else None
    if first_token:
        tid = first_token["token_id"]
        print(f"  market:   {btc_short[0]['question'][:60]}")
        print(f"  token_id: {tid}")

        bids = sorted(
            [OrderBookLevel(float(b["price"]), float(b["size"])) for b in DEMO_BOOK["bids"]],
            key=lambda x: x.price, reverse=True,
        )
        asks = sorted(
            [OrderBookLevel(float(a["price"]), float(a["size"])) for a in DEMO_BOOK["asks"]],
            key=lambda x: x.price,
        )
        book = OrderBookSnapshot(bids=bids, asks=asks)
        print_book(book)

    # Summary
    print(f"\n{DIV}")
    print("  結果サマリー")
    print(DIV)
    print(f"  Gamma API /events   : SKIP")
    print(f"  CLOB API  /markets  : DEMO ({len(all_raw)} markets)")
    print(f"  BTC関連             : {len(btc_all)}")
    print(f"  BTC短期             : {len(btc_short)}")
    print(f"  CLOB /book          : DEMO")
    print(DIV)
    print()
    print("  ライブ実行: python scripts/check_markets.py")
    print()


# ────────────────────────────────────────────────
async def main() -> None:
    if "--demo" in sys.argv:
        await run_demo()
    else:
        await run_live()


if __name__ == "__main__":
    asyncio.run(main())
