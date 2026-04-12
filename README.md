# Polymarket Arbitrage Detector

Implementation of **"Unravelling the Probabilistic Forest: Arbitrage in Prediction Markets"** (Saguillo, Ghafouri, Kiffer, Suarez-Tangil, AFT 2025) — [arXiv:2508.03474](https://arxiv.org/abs/2508.03474).

## Overview

Detects arbitrage opportunities on [Polymarket](https://polymarket.com) prediction markets:

1. **Single-Condition Arbitrage** — When YES + NO token prices deviate from $1.00
2. **NegRisk Intra-Event Arbitrage** — When the sum of YES prices across mutually exclusive outcomes deviates from $1.00
3. **Combinatorial Arbitrage** — Cross-market arbitrage exploiting logical dependencies between related markets (detected via text embeddings + LLM)

## Pipeline

```
Polymarket Gamma API
        |
   Fetch Events & Markets
        |
   +----+----+
   |         |
Intra-market  Combinatorial
   |              |
   |     Temporal Filtering
   |              |
   |     Topic Classification (Embeddings)
   |              |
   |     Semantic Similarity Search
   |              |
   |     LLM Relationship Extraction
   |              |
   +----+----+----+
        |
   Arbitrage Detection & Profit Calculation
        |
   Report / JSON Output
```

## Usage

```bash
# Install dependencies
pip install -r requirements.txt

# Run with demo data (no API access needed)
python main.py

# Run with live Polymarket data
python main.py --live

# Limit events and skip combinatorial (no embedding model/LLM needed)
python main.py --live --max-events 50 --skip-combinatorial

# JSON output
python main.py --json

# Verbose logging
python main.py --live -v
```

## Configuration

- **Embedding model**: Set `DEFAULT_EMBEDDING_MODEL` in `config.py` (default: `all-MiniLM-L6-v2`; paper uses `Linq-Embed-Mistral`)
- **LLM for relationship extraction**: Requires `ANTHROPIC_API_KEY` env var. Uses Claude for detecting logical dependencies between markets.
- **Thresholds**: Adjustable in `config.py` — minimum arbitrage threshold, similarity threshold, temporal distance, trading fees.

## Project Structure

```
main.py                                  # CLI entry point
polymarket_arbitrage/
  config.py                              # Configuration constants
  demo.py                               # Synthetic demo data
  pipeline.py                            # Full detection pipeline
  reporting.py                           # Report generation
  api/
    gamma_client.py                      # Polymarket Gamma API client
  models/
    market.py                            # Data models (Event, Market, Token, etc.)
  arbitrage/
    intra_market.py                      # Single-condition & NegRisk detection
    combinatorial.py                     # Cross-market arbitrage detection
  nlp/
    embeddings.py                        # Text embeddings & topic classification
    relationship.py                      # LLM-based relationship extraction
```
