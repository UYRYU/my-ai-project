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
from . import arbitrage, claude_analyzer, event_grouper, executor, mock_data, orderbook, polymarket, risk, trade_log
from .config import Config, load
from .positions import Book


CLAUDE_TICK_INTERVAL = 6


def _fetch_markets(cfg: Config) -> list[polymarket.Market]:
    if cfg.mock:
        return mock_data.markets()
    return polymarket.fetch_active_markets(cfg.sports_tags)


def _fetch_orderbook(cfg: Config, token_id: str) -> dict:
    if cfg.mock:
        return mock_data.orderbook(token_id)
    return polymarket.fetch_orderbook(cfg.polymarket_host, token_id)


def _verify_and_execute(opp, cfg: Config, book: Book) -> None:
    leg_token_ids = [t for t, _ in opp.legs]
    target_payout = cfg.max_position_usd
    quotes: list[orderbook.FillQuote] = []
    total_cost = 0.0
    for token_id in leg_token_ids:
        book_data = _fetch_orderbook(cfg, token_id)
        q = orderbook.average_fill_cost(book_data, "asks", target_payout)
        if q is None:
            trade_log.write("rejected_depth", slug=opp.market.slug, token=token_id)
            return
        quotes.append(q)
        total_cost += q.avg_price * target_payout
    real_edge = target_payout - total_cost
    if real_edge < cfg.min_edge * target_payout:
        trade_log.write(
            "rejected_real_edge",
            slug=opp.market.slug,
            snapshot_edge=opp.edge,
            real_edge_usd=real_edge,
        )
        return
    decision = risk.check(total_cost, len(quotes), cfg, book)
    if not decision.allow:
        trade_log.write("rejected_risk", reason=decision.reason, slug=opp.market.slug)
        return
    executor.execute(opp, cfg, book, quotes=quotes)


def run() -> None:
    cfg = load()
    claude = Anthropic(api_key=cfg.anthropic_api_key) if cfg.anthropic_api_key else None
    book = Book()

    print(
        f"[boot] dry_run={cfg.dry_run} mock={cfg.mock} once={cfg.once} "
        f"tags={cfg.sports_tags} min_edge={cfg.min_edge} claude={'on' if claude else 'off'}"
    )
    safe_cfg = {k: ("***" if "key" in k.lower() or "private" in k.lower() else v)
                for k, v in cfg.__dict__.items()}
    trade_log.write("boot", config=safe_cfg)

    tick = 0
    while True:
        tick += 1
        try:
            markets = _fetch_markets(cfg)
        except Exception as e:
            print(f"[tick {tick}] fetch failed: {e}")
            if cfg.once:
                return
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

        if claude is not None and tick % CLAUDE_TICK_INTERVAL == 0:
            try:
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

        if cfg.once:
            return
        time.sleep(cfg.poll_seconds)


if __name__ == "__main__":
    run()
