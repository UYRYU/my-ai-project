# Polymarket Arbitrage Bot

Implementation of **"Unravelling the Probabilistic Forest: Arbitrage in Prediction Markets"** ([arXiv:2508.03474](https://arxiv.org/abs/2508.03474)), extended into a live trading bot for Polymarket 5-minute crypto markets.

## What it does

Finds **guaranteed-profit** trades on Polymarket by detecting price constraint violations:

```
Market: "BTC above $104,500 in 5 min?"
  YES = $0.45,  NO = $0.48,  Total = $0.93

  Buy both → cost $0.93 → one ALWAYS pays $1 → profit $0.07 (7.5%)
```

## Quick Start

```bash
pip install -r requirements.txt

# Demo (no API needed)
python main.py

# $100 test simulation
python run_100usd_test.py

# Live bot (dry run — scan only)
python -m bot.run

# Live bot (real trades)
EXECUTION_MODE=live POLY_API_KEY=... INITIAL_CAPITAL=100 python -m bot.run
```

## Architecture

```
scan (60s loop)
  → Gamma API: fetch all active markets
  → detect: YES+NO != $1? sum(YES) != $1?
  → Kelly sizing: how much to bet?
  → risk check: utilization < 70%? no duplicates?
  → execute: place orders via CLOB API
  → monitor: wait for resolution (5 min)
  → auto-exit: claim payout, free capital
  → repeat
```

## Project Structure

```
bot/                          # Live trading bot
  run.py                      # Entry point: python -m bot.run
  scanner.py                  # 60s scan loop, Gamma API polling
  executor.py                 # Order execution (dry_run / live)
  portfolio.py                # Kelly sizing, risk limits, state tracking
  resolver.py                 # Auto-exit on market resolution

polymarket_arbitrage/         # Core detection engine
  arbitrage/
    intra_market.py           # Single-condition + NegRisk arb detection
    combinatorial.py          # Cross-market arb (embedding + LLM)
  core/
    primitives.py             # Domain-agnostic: Instrument, Outcome, Opportunity
    detectors.py              # Generic constraint-violation detectors
    similarity.py             # Embedding-based market similarity
  api/
    gamma_client.py           # Polymarket Gamma API client (async)
  nlp/
    embeddings.py             # Topic classification (TF-IDF / sentence-transformers)
    relationship.py           # LLM relationship extraction
  adapters/                   # Other domains (Sports, DeFi, Options)
  config.py                   # Thresholds, fees, model settings

Simulations:
  run_100usd_test.py          # $100 test run paper trade
  run_5min_crypto_sim.py      # 5-min crypto arb full day sim
  run_50man_strategy.py       # 50万円 strategy with compound growth
  run_paper_demo.py           # Full pipeline demo (paper reproduction)
  run_all_domains.py          # Multi-domain arb demo (4 domains)
  run_profitability.py        # Profitability analysis across domains
```

## Deployment Plan

```
Phase 1: $100 test (2 weeks)
  → VPS (US East) + dry_run mode
  → Verify arb detection on live data
  → Switch to live with $5-20/trade

Phase 2: 50万円 ($3,145) full deploy
  → Increase INITIAL_CAPITAL + POSITION_SIZE
  → Target: 月20-50万円
```

## Environment Variables

```bash
SCAN_INTERVAL=60          # scan frequency (seconds)
MIN_PROFIT=0.015          # minimum 1.5% profit to trade
MIN_VOLUME=50000          # minimum market volume ($)
INITIAL_CAPITAL=100       # starting capital ($)
MIN_TRADE_SIZE=5          # minimum trade size ($)
MAX_SINGLE_TRADE_PCT=0.20 # max 20% of equity per trade
MAX_UTILIZATION=0.80      # max 80% of capital deployed
MAX_CONCURRENT=5          # max simultaneous positions
EXECUTION_MODE=dry_run    # dry_run or live
POLY_API_KEY=             # Polymarket API key
WEBHOOK_URL=              # Discord/Telegram alerts
```

## References

- [arXiv:2508.03474](https://arxiv.org/abs/2508.03474) — Saguillo et al., "Unravelling the Probabilistic Forest" (AFT 2025)
- [Polymarket Docs](https://docs.polymarket.com) — Gamma API, CLOB API
- [py-clob-client](https://github.com/Polymarket/py-clob-client) — Official Python SDK
