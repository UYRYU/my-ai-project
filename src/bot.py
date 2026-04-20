"""Main loop — hot path.

Hot loop is purely mechanical: fetch markets → quality filter → arb
scan → depth-verify → risk check → execute. No Claude in the hot path
— Claude latency and cost kill arb edges. Use `python -m src.analyze`
for offline analysis of trades.jsonl.

Two-stage scan for the one strategy that's still tractable:
1. Gamma snapshot → filter illiquid/stale → sum-of-asks < 1 candidate
2. CLOB orderbook → VWAP verify → risk check → atomic execute
"""

from __future__ import annotations

import time

from . import arbitrage, executor, market_filter, mock_data, orderbook, polymarket, risk, trade_log
from .config import Config, load
from .positions import Book
from .risk import DailyCounters


def _fetch_markets(cfg: Config) -> list[polymarket.Market]:
    if cfg.mock:
        return mock_data.markets()
    return polymarket.fetch_active_markets(cfg.sports_tags)


def _fetch_orderbook(cfg: Config, token_id: str) -> dict:
    if cfg.mock:
        return mock_data.orderbook(token_id)
    return polymarket.fetch_orderbook(cfg.polymarket_host, token_id)


def _verify_and_execute(opp, cfg: Config, book: Book, counters: DailyCounters) -> None:
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

    real_edge_usd = target_payout - total_cost
    real_edge_pct = real_edge_usd / target_payout
    if real_edge_pct < cfg.min_edge:
        trade_log.write(
            "rejected_real_edge",
            slug=opp.market.slug,
            snapshot_edge=opp.edge,
            real_edge_pct=real_edge_pct,
            real_edge_usd=real_edge_usd,
        )
        return

    decision = risk.check(total_cost, len(quotes), cfg, book, counters)
    if not decision.allow:
        trade_log.write("rejected_risk", reason=decision.reason, slug=opp.market.slug)
        return

    executor.execute(opp, cfg, book, quotes=quotes)
    counters.baskets_today += 1


def run() -> None:
    cfg = load()
    book = Book()
    counters = DailyCounters()

    safe_cfg = {
        k: ("***" if "key" in k.lower() or "private" in k.lower() else v)
        for k, v in cfg.__dict__.items()
    }
    print(
        f"[boot] dry_run={cfg.dry_run} mock={cfg.mock} once={cfg.once} "
        f"tags={cfg.sports_tags} min_edge={cfg.min_edge} max_pos=${cfg.max_position_usd}"
    )
    trade_log.write("boot", config=safe_cfg)

    tick = 0
    while True:
        tick += 1
        try:
            raw_markets = _fetch_markets(cfg)
        except Exception as e:
            print(f"[tick {tick}] fetch failed: {e}")
            if cfg.once:
                return
            time.sleep(cfg.poll_seconds)
            continue

        markets, rejected = market_filter.filter_tradeable(raw_markets)
        candidates = arbitrage.scan(markets, cfg.min_edge)

        print(
            f"[tick {tick}] raw={len(raw_markets)} tradeable={len(markets)} "
            f"candidates={len(candidates)} pos={len(book.positions)} "
            f"exposure=${book.gross_exposure_usd():.2f} "
            f"pnl=${book.realized_pnl:.2f} baskets_today={counters.baskets_today}"
        )
        if rejected:
            trade_log.write("filter_rejections", counts=rejected)

        for opp in candidates:
            if opp.kind == "same_market_sum_under_one":
                _verify_and_execute(opp, cfg, book, counters)

        if cfg.once:
            return
        time.sleep(cfg.poll_seconds)


if __name__ == "__main__":
    run()
