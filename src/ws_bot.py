"""Async WebSocket-driven bot.

Architecture:
- `discovery_loop` — periodic Gamma REST fetch → filter → update
  subscribed asset list (slow, ~30s cadence)
- `ws_task` — CLOB market channel subscription → OrderbookCache
- `trading_loop` — reads the cache tick-by-tick, detects arbs,
  depth-verifies, risk-checks, and executes
- `metrics_server` — exposes /metrics for Prometheus on :9100

Run:
    python -m src.ws_bot
"""

from __future__ import annotations

import asyncio
import time

from . import arbitrage, executor, market_filter, mock_data, orderbook, polymarket, risk, trade_log
from .clob_ws import CLOBWebSocket, OrderbookCache
from .config import Config, load
from .metrics import Metrics, serve as serve_metrics
from .positions import Book
from .risk import DailyCounters


DISCOVERY_EVERY_SECONDS = 30.0
TRADING_TICK_SECONDS = 0.1
MAX_BOOK_AGE_SECONDS = 5.0


async def _discovery_loop(cfg: Config, state: dict) -> None:
    while True:
        try:
            if cfg.mock:
                markets = mock_data.markets()
            else:
                markets = await asyncio.to_thread(
                    polymarket.fetch_active_markets, cfg.sports_tags
                )
            tradeable, _ = market_filter.filter_tradeable(markets)
            state["markets"] = tradeable
            state["token_to_market"] = {
                o.token_id: m for m in tradeable for o in m.outcomes
            }
            new_ids = sorted({o.token_id for m in tradeable for o in m.outcomes})
            if new_ids != state.get("asset_ids", []):
                state["asset_ids"] = new_ids
                state["asset_ids_changed"].set()
            state["metrics"].set("tradeable_markets", len(tradeable))
            state["metrics"].set("subscribed_assets", len(new_ids))
        except Exception as e:
            print(f"[discovery] failed: {e}")
            state["metrics"].inc("discovery_errors")
        await asyncio.sleep(DISCOVERY_EVERY_SECONDS)


async def _ws_supervisor(cfg: Config, cache: OrderbookCache, state: dict) -> None:
    if cfg.mock:
        for m in mock_data.markets():
            for o in m.outcomes:
                cache.apply_snapshot(o.token_id, mock_data.orderbook(o.token_id))
        return  # mock mode: snapshot once, no live WS

    while True:
        asset_ids = state.get("asset_ids") or []
        if not asset_ids:
            await state["asset_ids_changed"].wait()
            state["asset_ids_changed"].clear()
            continue
        ws = CLOBWebSocket(cache)
        task = asyncio.create_task(ws.run(asset_ids))
        await state["asset_ids_changed"].wait()
        state["asset_ids_changed"].clear()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def _try_arb_from_cache(
    market: polymarket.Market,
    cache: OrderbookCache,
    target_payout_usd: float,
) -> tuple[list[orderbook.FillQuote], float] | None:
    quotes: list[orderbook.FillQuote] = []
    total_cost = 0.0
    for o in market.outcomes:
        book = cache.get(o.token_id, max_age_seconds=MAX_BOOK_AGE_SECONDS)
        if book is None:
            return None
        q = orderbook.average_fill_cost(book, "asks", target_payout_usd)
        if q is None:
            return None
        quotes.append(q)
        total_cost += q.avg_price * target_payout_usd
    return quotes, total_cost


async def _trading_loop(
    cfg: Config,
    cache: OrderbookCache,
    state: dict,
    book: Book,
    counters: DailyCounters,
) -> None:
    metrics = state["metrics"]
    while True:
        tick_start = time.time()
        markets: list[polymarket.Market] = state.get("markets", [])
        metrics.set("positions_open", len(book.positions))
        metrics.set("gross_exposure_usd", book.gross_exposure_usd())
        metrics.set("realized_pnl_usd", book.realized_pnl)
        metrics.set("baskets_today", counters.baskets_today)

        for market in markets:
            result = _try_arb_from_cache(market, cache, cfg.max_position_usd)
            if result is None:
                continue
            quotes, total_cost = result
            real_edge_pct = (cfg.max_position_usd - total_cost) / cfg.max_position_usd
            if real_edge_pct < cfg.min_edge:
                continue
            decision = risk.check(total_cost, len(quotes), cfg, book, counters)
            if not decision.allow:
                trade_log.write("rejected_risk", reason=decision.reason, slug=market.slug)
                metrics.inc("rejected_risk")
                continue
            opp = arbitrage.Opportunity(
                kind="ws_same_market_sum_under_one",
                market=market,
                legs=tuple((q.token_id, q.avg_price) for q in quotes),
                edge=real_edge_pct,
                note=f"WS cached, cost {total_cost:.4f}",
            )
            await asyncio.to_thread(executor.execute, opp, cfg, book, quotes)
            counters.baskets_today += 1
            metrics.inc("baskets_executed")

        # Latency reporting
        metrics.set("trading_tick_ms", (time.time() - tick_start) * 1000)
        if cfg.once:
            return
        await asyncio.sleep(TRADING_TICK_SECONDS)


async def main() -> None:
    cfg = load()
    book = Book()
    counters = DailyCounters()
    cache = OrderbookCache()
    metrics = Metrics()

    state = {
        "markets": [],
        "asset_ids": [],
        "token_to_market": {},
        "asset_ids_changed": asyncio.Event(),
        "metrics": metrics,
    }

    safe_cfg = {
        k: ("***" if any(s in k.lower() for s in ("key", "private", "secret", "passphrase")) else v)
        for k, v in cfg.__dict__.items()
    }
    print(f"[ws_boot] dry_run={cfg.dry_run} mock={cfg.mock} min_edge={cfg.min_edge}")
    trade_log.write("ws_boot", config=safe_cfg)

    # Seed one discovery pass before starting trading
    if cfg.mock:
        state["markets"] = mock_data.markets()
        state["asset_ids"] = [o.token_id for m in state["markets"] for o in m.outcomes]
    else:
        try:
            markets = await asyncio.to_thread(polymarket.fetch_active_markets, cfg.sports_tags)
            tradeable, _ = market_filter.filter_tradeable(markets)
            state["markets"] = tradeable
            state["asset_ids"] = [o.token_id for m in tradeable for o in m.outcomes]
        except Exception as e:
            print(f"[seed] discovery failed: {e}")

    tasks = [
        asyncio.create_task(_discovery_loop(cfg, state)),
        asyncio.create_task(_ws_supervisor(cfg, cache, state)),
        asyncio.create_task(_trading_loop(cfg, cache, state, book, counters)),
    ]
    if not cfg.once:
        tasks.append(asyncio.create_task(serve_metrics(metrics)))

    try:
        if cfg.once:
            # Wait a moment for the trading loop to react, then exit
            await asyncio.sleep(0.5)
            return
        await asyncio.gather(*tasks)
    finally:
        for t in tasks:
            t.cancel()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
