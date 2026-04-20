"""Main loop.

Two-stage scan:
1. Cheap Gamma snapshot scan to surface candidates (snapshot prices,
   may be stale by seconds — used for filtering only).
2. For each candidate, fetch the live CLOB orderbook and compute a
   depth-verified VWAP cost. Only execute if real edge survives.

Claude scout runs less often (every N ticks) over events grouped by the
local heuristic. It's expensive — ~$0.01-$0.05 per call on Opus 4.7 with
caching — so we batch.
"""

import time
from anthropic import Anthropic
from . import arbitrage, claude_analyzer, event_grouper, executor, orderbook, polymarket, risk, trade_log
from .config import load
from .positions import Book


CLAUDE_TICK_INTERVAL = 6  # ~ every 6 ticks


def _verify_and_execute(opp, cfg, book) -> None:
    leg_token_ids = [t for t, _ in opp.legs]
    target_payout = cfg.max_position_usd  # we'll size so winning leg pays this
    quote = orderbook.quote_basket_cost(cfg.polymarket_host, leg_token_ids, target_payout)
    if quote is None:
        trade_log.write("rejected_depth", slug=opp.market.slug, kind=opp.kind)
        return
    total_cost, fills = quote
    real_edge = target_payout - total_cost
    if real_edge < cfg.min_edge * target_payout:
        trade_log.write(
            "rejected_real_edge",
            slug=opp.market.slug,
            snapshot_edge=opp.edge,
            real_edge_usd=real_edge,
        )
        return
    decision = risk.check(total_cost, len(fills), cfg, book)
    if not decision.allow:
        trade_log.write("rejected_risk", reason=decision.reason, slug=opp.market.slug)
        return
    executor.execute(opp, cfg, book, quotes=fills)


def run() -> None:
    cfg = load()
    claude = Anthropic(api_key=cfg.anthropic_api_key)
    book = Book()

    print(f"[boot] dry_run={cfg.dry_run} tags={cfg.sports_tags} min_edge={cfg.min_edge}")
    trade_log.write("boot", config=cfg.__dict__)

    tick = 0
    while True:
        tick += 1
        try:
            markets = polymarket.fetch_active_markets(cfg.sports_tags)
        except Exception as e:
            print(f"[tick {tick}] fetch failed: {e}")
            time.sleep(cfg.poll_seconds)
            continue

        events = event_grouper.group_by_event(markets)
        candidates = arbitrage.scan(markets, cfg.min_edge)
        print(
            f"[tick {tick}] markets={len(markets)} events={len(events)} "
            f"candidates={len(candidates)} pos={len(book.positions)} "
            f"exposure=${book.gross_exposure_usd():.2f} pnl=${book.realized_pnl:.2f}"
        )

        for opp in candidates:
            if opp.kind == "same_market_sum_under_one":
                _verify_and_execute(opp, cfg, book)

        if tick % CLAUDE_TICK_INTERVAL == 0:
            try:
                # Only feed Claude grouped events — it's where cross-market
                # value lives and it keeps the prompt small enough to cache.
                grouped_markets = [m for ms in events.values() for m in ms]
                baskets = claude_analyzer.find_correlated_baskets(claude, grouped_markets)
                for b in baskets:
                    print(f"[claude] basket sum={b.implied_sum:.4f} — {b.rationale[:80]}")
                    trade_log.write(
                        "claude_basket",
                        rationale=b.rationale,
                        implied_sum=b.implied_sum,
                        legs=list(b.legs),
                    )
            except Exception as e:
                print(f"[tick {tick}] claude scan failed: {e}")

        time.sleep(cfg.poll_seconds)


if __name__ == "__main__":
    run()
