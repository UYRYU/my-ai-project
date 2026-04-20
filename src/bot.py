import time
from anthropic import Anthropic
from . import arbitrage, claude_analyzer, executor, polymarket
from .config import load


def run() -> None:
    cfg = load()
    claude = Anthropic(api_key=cfg.anthropic_api_key)

    print(f"[boot] dry_run={cfg.dry_run} tags={cfg.sports_tags} min_edge={cfg.min_edge}")

    tick = 0
    while True:
        tick += 1
        try:
            markets = polymarket.fetch_active_markets(cfg.sports_tags)
        except Exception as e:
            print(f"[tick {tick}] fetch failed: {e}")
            time.sleep(cfg.poll_seconds)
            continue

        print(f"[tick {tick}] {len(markets)} markets pulled")

        for opp in arbitrage.scan(markets, cfg.min_edge):
            executor.execute(opp, cfg)

        if tick % 6 == 0:  # call Claude ~every minute on default 10s tick
            try:
                baskets = claude_analyzer.find_correlated_baskets(claude, markets)
                for b in baskets:
                    print(f"[claude] basket sum={b.implied_sum:.4f} — {b.rationale}")
            except Exception as e:
                print(f"[tick {tick}] claude scan failed: {e}")

        time.sleep(cfg.poll_seconds)


if __name__ == "__main__":
    run()
